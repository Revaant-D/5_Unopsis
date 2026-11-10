"""
A8 RAG pipeline: corpus -> chunking -> embeddings -> retrieval -> generation -> evaluation.

Built as a module so each piece can be tested on its own; the notebook imports it and also
prints the source of the functions it calls, so the implementation is visible there too.

Design notes that matter for the write-up:
  * Chunking never splits a sentence. The fixed-length strategy packs whole sentences up to a
    word budget rather than slicing at an exact offset, because a chunk ending mid-clause
    retrieves badly and reads worse once it reaches the prompt.
  * The corpus spells numbers out ("eight dollars") while the test queries use digits ("$8").
    That mismatch is deliberate: it means retrieval cannot succeed by lexical overlap alone and
    actually has to carry semantic signal, which is the thing being compared across embedding
    sizes. Answer grading accepts either form.
"""
import json, pathlib, re, time, urllib.request
import numpy as np

CORPUS_DIR = pathlib.Path(__file__).parent / "corpus"
# Granite-3.3-2B-Instruct: evaluated in A6 (0.692 lane accuracy, best below 4B, tied with Phi-4-mini) and A7 Part 1
# (9.76/10, 2nd of 15, best in the Medium 2-4B band), and the model the Unopsis app runs.
# Served by Ollama as a 4-bit (Q4_K_M) build of ibm-granite/granite-3.3-2b-instruct, the same
# weights A6/A7 ran in full precision through transformers. Held constant across every experiment.
GEN_MODEL = "granite3.3:2b"
OLLAMA = "http://localhost:11434/api/generate"

EMBEDDERS = [
    ("small",  "sentence-transformers/all-MiniLM-L6-v2",  384),
    ("medium", "sentence-transformers/all-mpnet-base-v2",  768),
    ("large",  "BAAI/bge-large-en-v1.5",                  1024),
]


# ----------------------------------------------------------------- corpus
def load_documents(corpus_dir=CORPUS_DIR):
    """Each file is one document: a title plus a list of paragraphs.

    A paragraph is defined as text between blank lines, which is how the source files are
    authored. This is the unit every chunking strategy below builds from.
    """
    docs = []
    for p in sorted(pathlib.Path(corpus_dir).glob("*.md")):
        text = p.read_text(encoding="utf-8")   # explicit: Windows would otherwise use cp1252
        title = next((l.lstrip("# ").strip() for l in text.splitlines() if l.startswith("#")), p.stem)
        body = re.sub(r"^#.*$", "", text, flags=re.M).strip()
        paras = [re.sub(r"\s+", " ", x).strip() for x in re.split(r"\n\s*\n", body) if x.strip()]
        docs.append({"id": p.stem, "title": title, "paragraphs": paras})
    return docs


def sentences(text):
    """Split on sentence terminators followed by a capital. Keeps the terminator attached."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text) if s.strip()]


# ----------------------------------------------------------------- chunking (3 strategies)
def chunk_fixed(docs, budget=120):
    """1. Fixed-length: pack whole sentences up to a `budget` word limit, never splitting one.

    Chunks do not cross document boundaries, so unrelated topics are never merged.
    """
    out = []
    for d in docs:
        sents, cur, n = [s for p in d["paragraphs"] for s in sentences(p)], [], 0
        for s in sents:
            w = len(s.split())
            if cur and n + w > budget:
                out.append(_chunk(d, " ".join(cur), "fixed"))
                cur, n = [], 0
            cur.append(s); n += w
        if cur:
            out.append(_chunk(d, " ".join(cur), "fixed"))
    return out


def chunk_overlap(docs):
    """2. Overlapping paragraph: a sliding window of two adjacent paragraphs, stride one.

    Chunk 1 = P1+P2, chunk 2 = P2+P3, ... so every paragraph except the first and last appears
    in two chunks. Overlap is implemented at paragraph granularity, which keeps each chunk a
    whole number of complete thoughts. Windows never span two documents.
    """
    out = []
    for d in docs:
        ps = d["paragraphs"]
        if len(ps) == 1:
            out.append(_chunk(d, ps[0], "overlap")); continue
        for i in range(len(ps) - 1):
            out.append(_chunk(d, ps[i] + " " + ps[i + 1], "overlap"))
    return out


def chunk_hybrid(docs, floor=95):
    """3. Hybrid/strategic: title-augmented paragraphs with an adaptive merge.

    Two ideas combined:
      (a) Every chunk is prefixed with its document title. A bare paragraph saying "eight
          dollars per month" carries no signal about WHAT costs eight dollars; prefixing
          "Plans and Pricing" puts the topic inside the embedded text where retrieval can use
          it. This is the main bet of the strategy.
      (b) Paragraphs shorter than `floor` words are merged with the following paragraph, so the
          index holds no stub chunks that match weakly on everything.
    """
    out = []
    for d in docs:
        buf = []
        for p in d["paragraphs"]:
            buf.append(p)
            if len(" ".join(buf).split()) >= floor:
                out.append(_chunk(d, " ".join(buf), "hybrid", titled=True)); buf = []
        if buf:
            if out and out[-1]["doc_id"] == d["id"]:
                out[-1]["text"] += " " + " ".join(buf)          # tail too short to stand alone
            else:
                out.append(_chunk(d, " ".join(buf), "hybrid", titled=True))
    return out


def _chunk(d, text, strategy, titled=False):
    return {"doc_id": d["id"], "doc_title": d["title"], "strategy": strategy,
            "text": (f"{d['title']}. {text}" if titled else text), "words": len(text.split())}


STRATEGIES = {"fixed": chunk_fixed, "overlap": chunk_overlap, "hybrid": chunk_hybrid}


# ----------------------------------------------------------------- embeddings + store
class VectorStore:
    """Normalised embedding matrix + cosine similarity search.

    Cosine similarity on L2-normalised vectors is a dot product, so the whole search is one
    matrix-vector multiply. At this corpus size that is faster than any index structure and
    exact, so there is no recall/latency trade-off to report.
    """

    def __init__(self, model, chunks, batch=32):
        self.model, self.chunks = model, chunks
        t0 = time.perf_counter()
        self.M = model.encode([c["text"] for c in chunks], batch_size=batch,
                              normalize_embeddings=True, show_progress_bar=False)
        self.index_sec = time.perf_counter() - t0
        self.dim = int(self.M.shape[1])

    def search(self, query, k=3):
        t0 = time.perf_counter()
        q = self.model.encode([query], normalize_embeddings=True)[0]
        t_embed = time.perf_counter() - t0
        t1 = time.perf_counter()
        sims = self.M @ q
        order = np.argsort(-sims)[:k]
        t_search = time.perf_counter() - t1
        hits = [{**self.chunks[i], "score": float(sims[i]), "rank": r + 1}
                for r, i in enumerate(order)]
        return hits, t_embed, t_search


# ----------------------------------------------------------------- generation
SYSTEM = ("You are a support assistant for Unopsis. Answer the question using only the context "
          "provided. If the context does not contain the answer, reply exactly: NOT IN CONTEXT. "
          "Answer in one or two sentences and state any number exactly as the context gives it.")


def build_prompt(query, hits):
    ctx = "\n\n".join(f"[{h['rank']}] ({h['doc_title']}) {h['text']}" for h in hits)
    return f"{SYSTEM}\n\nContext:\n{ctx}\n\nQuestion: {query}\nAnswer:"


def generate(prompt, model=GEN_MODEL, num_predict=160, seed=42, timeout=180):
    body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0, "seed": seed, "num_predict": num_predict}}).encode()
    req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    return {"text": d.get("response", "").strip(), "sec": time.perf_counter() - t0,
            "eval_count": d.get("eval_count"), "done_reason": d.get("done_reason"),
            # prompt_eval_count is the measured input token count. Part 4.1 needs it: on a
            # hosted API the prompt is what you pay for, and top-k is what sets its size.
            "prompt_eval_count": d.get("prompt_eval_count"),
            "prompt_chars": len(prompt)}


# ----------------------------------------------------------------- test queries + grading
# gold_doc   = the document that actually answers the question
# gold       = accepted surface forms of the correct fact (the corpus spells numbers out, a
#              model may answer in digits, so both are accepted)
# wrong      = values that CONTRADICT the answer. Kept deliberately short and unambiguous:
#              a related-but-different figure the model might confuse for the answer. Facts
#              that are merely additional (the student price alongside the Pro price) are not
#              listed, because volunteering them is not an error.
DIRECT_QUERIES = [
    {"id": "Q1", "text": "How much does the Pro plan cost per month?",
     "gold_doc": "03-pricing", "gold": ["eight dollars", "$8", "8 dollars"],
     "wrong": ["twenty dollars", "$20"]},
    {"id": "Q2", "text": "How long are notifications kept on the free plan?",
     "gold_doc": "05-privacy", "gold": ["seven days", "7 days"],
     "wrong": ["ninety days", "90 days", "three hundred and sixty five", "365 days"]},
    {"id": "Q3", "text": "What is the default priority threshold for immediate delivery?",
     "gold_doc": "04-filtering", "gold": ["forty", "40"], "wrong": []},
    {"id": "Q4", "text": "What uptime does the Team plan commit to each month?",
     "gold_doc": "06-support", "gold": ["ninety nine point nine", "99.9"], "wrong": []},
    {"id": "Q5", "text": "How many API requests per minute can a Pro account make?",
     "gold_doc": "07-architecture", "gold": ["sixty", "60"],
     "wrong": ["six hundred", "600"]},
    {"id": "Q6", "text": "Which connector delivers events by webhook instead of polling?",
     "gold_doc": "02-connectors", "gold": ["pagerduty"], "wrong": []},
    {"id": "Q7", "text": "How long is the refund window on a paid plan?",
     "gold_doc": "03-pricing", "gold": ["fourteen day", "14 day"], "wrong": ["thirty day"]},
]

# A second set, written to be hard on purpose. The direct set above saturates: on a corpus of
# eight topically distinct documents, a question that reuses the corpus's own wording is found
# by every embedding model at top-3, so every configuration scores full marks and the
# comparison the assignment asks for has nothing to measure. These queries instead use the
# phrasing a real user would reach for, and each one competes against a near neighbour
# elsewhere in the corpus:
#   H1 asks about refunds without using the word "refund"
#   H2 "how long do I have" collides with the refund window and three retention windows
#   H3 requires knowing which PLAN gates a feature, i.e. joining two documents
#   H4 asks for support channels, where the corpus states them alongside what is NOT offered
#   H5 "seven days" appears in both the connector-expiry and data-retention documents
#   H6 describes a symptom ("quiet overnight") rather than naming the feature
#   H7 "five" appears as five retries, five megabytes and five business days
HARD_QUERIES = [
    {"id": "H1", "text": "If I cancel my subscription, can I get my money back?",
     "gold_doc": "03-pricing", "gold": ["fourteen day", "14 day"], "wrong": ["thirty day"]},
    {"id": "H2", "text": "How long do I have to request a service credit after an outage?",
     "gold_doc": "06-support", "gold": ["thirty days", "30 days"],
     "wrong": ["fourteen days", "14 days"]},
    {"id": "H3", "text": "Which plan do I need if my organisation requires single sign on?",
     "gold_doc": "05-privacy", "gold": ["team"], "wrong": []},
    {"id": "H4", "text": "What are the two ways to get in touch with support?",
     "gold_doc": "06-support", "gold": ["contact form"], "wrong": []},
    {"id": "H5", "text": "What happens if a connector loses its authorisation?",
     "gold_doc": "02-connectors", "gold": ["degraded"], "wrong": []},
    {"id": "H6", "text": "Why would my notifications go silent overnight?",
     "gold_doc": "04-filtering", "gold": ["quiet hours"], "wrong": []},
    {"id": "H7", "text": "How many times does a failed webhook get retried?",
     "gold_doc": "07-architecture", "gold": ["five times", "five attempts", "5 times", "five"],
     "wrong": []},
]

for _q in DIRECT_QUERIES:
    _q["difficulty"] = "direct"
for _q in HARD_QUERIES:
    _q["difficulty"] = "hard"

QUERIES = DIRECT_QUERIES + HARD_QUERIES

NOT_IN_CTX = "not in context"


def _norm(s):
    return re.sub(r"\s+", " ", s.lower())


def grade_context(q, hits):
    """0-5 for retrieved context, plus the rank at which the answer first appears.

    5 = a retrieved chunk actually contains the answer
    3 = the right document was retrieved, but not the part containing the answer
    0 = the right document was not retrieved at all
    """
    rank = next((h["rank"] for h in hits
                 if any(g in _norm(h["text"]) for g in q["gold"])), None)
    from_gold_doc = any(h["doc_id"] == q["gold_doc"] for h in hits)
    score = 5 if rank else (3 if from_gold_doc else 0)
    return score, rank, from_gold_doc


def grade_answer(q, answer):
    """0-5 for the generated answer.

    5 = states the correct fact
    1 = attempted an answer, on topic, but never states the fact
    0 = abstained (NOT IN CONTEXT), returned nothing, or answered with a contradicting fact

    Revised after the first run: the earlier version docked a point when the answer stated the
    correct fact AND mentioned a different figure. That is wrong. "Pro is eight dollars a
    month, Team is twenty" answers the question and adds useful contrast; penalising it
    measured verbosity, not accuracy. A conflicting figure is still recorded in
    `also_states_conflicting` so it stays visible in the data, it just does not move the score.
    """
    a = _norm(answer)
    if not a or NOT_IN_CTX in a:
        return 0, "abstained", False
    has_gold = any(g in a for g in q["gold"])
    has_wrong = any(w in a for w in q["wrong"])
    if has_gold:
        return 5, "correct", has_wrong
    if has_wrong:
        return 0, "states a contradicting fact", True
    return 1, "on topic, fact missing", False


def run_config(store, queries=QUERIES, k=3, gen_model=GEN_MODEL):
    """One embedding model x one chunking strategy, across every query."""
    rows = []
    for q in queries:
        hits, t_embed, t_search = store.search(q["text"], k=k)
        prompt = build_prompt(q["text"], hits)
        g = generate(prompt, model=gen_model)
        cq, rank, gold_doc_hit = grade_context(q, hits)
        aq, verdict, conflicting = grade_answer(q, g["text"])
        rows.append({
            "query_id": q["id"], "query": q["text"], "top_k": k,
            "retrieved": [{"doc_id": h["doc_id"], "doc_title": h["doc_title"], "rank": h["rank"],
                           "score": round(h["score"], 4), "words": h["words"],
                           "text": h["text"]} for h in hits],
            "gold_doc": q["gold_doc"], "gold_doc_retrieved": gold_doc_hit,
            "answer_rank": rank, "context_quality": cq,
            "answer": g["text"], "answer_quality": aq, "verdict": verdict,
            "also_states_conflicting": conflicting, "difficulty": q.get("difficulty", "direct"),
            "latency": {"embed_query": round(t_embed, 4), "search": round(t_search, 5),
                        "generate": round(g["sec"], 2),
                        "total": round(t_embed + t_search + g["sec"], 2)},
            "gen_eval_count": g["eval_count"],
            "prompt_tokens": g["prompt_eval_count"], "prompt_chars": g["prompt_chars"],
            "context_words": sum(h["words"] for h in hits),
        })
    return rows
