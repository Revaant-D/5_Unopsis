# A8 — RAG System Analysis

**Knowledge base:** 8 documents, 32 paragraphs (87–110 words each), 3,093 words: product and
operations documentation for *Unopsis*, our team's notification-aggregation project.

**Generation model, held constant across all 9 configurations:** IBM **Granite-3.3-2B-Instruct**
(`granite3.3:2b` in Ollama, temperature 0, seed 42). This is the model our team selected in
**A6** (0.692 lane accuracy on our triage task, the best below 4B, tied with the larger 3.8B Phi-4-mini) and **A7 Part 1** (9.76/10,
2nd of the 15 models benchmarked and the best in the Medium 2–4B band). It is also the model the
Unopsis web app runs. Ollama serves a 4-bit (Q4_K_M) build of the same weights that A6 and A7 ran
in full precision through `transformers`. Only the embedding model and the chunking strategy vary
between configurations, so every difference below is attributable to those two components.

**Embedding models:** small = `all-MiniLM-L6-v2` (384-d, 22M parameters) · medium =
`all-mpnet-base-v2` (768-d, 110M) · large = `BAAI/bge-large-en-v1.5` (1024-d, 335M).

**Retrieval:** exact cosine similarity over L2-normalised vectors, top-k = 3.

> **About this version.** The first submission generated with `llama3.2:3b`, which is not one of
> the models our team benchmarked in A6/A7. This version replaces it with Granite-3.3-2B and
> re-runs every experiment end to end. Retrieval numbers (context quality, MRR, recall, Step 2.5)
> are unchanged, because they do not depend on the generator. Every answer-side number, failure
> and conclusion below comes from the Granite run in `rag_system.ipynb` and
> `results/notebook_run.json`. Where a conclusion matches or differs from the first run, the
> text says so: that is a free robustness check on how far these small differences generalise.

All latencies were measured on a 6-core Windows laptop CPU, with the embedding model and the
generation model sharing that CPU.

---

## How quality was scored

Two mechanical 0–5 scores, kept separate on purpose.

**Retrieved context quality**: *did retrieval put the answer in front of the model?*
5 = a retrieved chunk contains the answer · 3 = the right document came back, but not the part
with the answer · 0 = the right document was never retrieved.

**Answer quality**: *did the model then use it?*
5 = states the correct fact · 1 = on topic, but never states the fact · 0 = abstained (`NOT IN
CONTEXT`), or answered with a contradicting fact.

**MRR** (reciprocal rank of the first chunk containing the answer) is reported too, because
several configurations reach context quality 5.00 and rank is then all that separates them.

**Known grader limits, found while reading the failures (Part 3).** Both are mechanical
string-matching artifacts, reported rather than patched after the fact.
1. One context score is a false positive. For H7 under medium + hybrid, the answer token "five"
   matched "five *business days*" in the support document, so the row scored context 5 although
   the architecture document holding the answer was never retrieved. **Corrected, medium +
   hybrid is context 4.64 and MRR 0.714** (not 5.00 / 0.786). Its gold-document recall of 13/14
   already shows the miss. No other row is affected: in every other row the credited chunk comes
   from the right document.
2. One answer that stated the correct fact but began with "NOT IN CONTEXT." was scored as an
   abstention (H1, large + fixed).

### The two query sets

**Direct (Q1–Q7)** phrase the question the way the corpus phrases the answer. **Hard (H1–H7)**
use the wording a real user would reach for, and each one competes with a near neighbour
elsewhere in the corpus:
* "how long do I have" collides with the refund window and three retention windows;
* "five" appears as five retries, five megabytes and five business days;
* H3 needs two documents joined to learn which plan gates a feature.

The hard set was written after the direct set saturated in our first runs.

With Granite, both sets produce failures, of different kinds:
* **Direct failures** come from the generator picking the wrong number out of a correct chunk
  (Q5, Q7) and from chunking (Q1, Q2).
* **Hard failures** come from query formulation (H6), a retrieval collision (H7) and one
  answer-format slip (H1).

---

## Step 2.2 — Evaluation table: all 9 configurations

14 queries each, 126 rows. **Every row, with its retrieved chunks, answer, scores, latency and a
note, is printed in `rag_system.ipynb`** ("Every configuration" cell, Step 2.2). The full chunk
text for the best and worst configurations is printed above it. All 126 rows are saved in
`results/notebook_run.json`.

| Embedding | Dim | Chunking | Chunks | Context | Answer | MRR | Gold-doc recall | Retrieval ms | Gen s | Total s |
|---|---|---|---|---|---|---|---|---|---|---|
| small | 384 | fixed | 32 | 5.00 | 4.64 | 0.881 | 14/14 | 132 | 9.79 | 9.92 |
| small | 384 | overlap | 24 | 4.64 | 4.64 | 0.929 | 13/14 | 75 | 15.33 | 15.40 |
| small | 384 | hybrid | 21 | 5.00 | 4.71 | 0.917 | 14/14 | 119 | 13.99 | 14.11 |
| medium | 768 | fixed | 32 | 4.86 | 4.36 | 0.821 | 14/14 | 850 | 9.69 | 10.53 |
| medium | 768 | overlap | 24 | 5.00 | **5.00** | 0.881 | 14/14 | 287 | 14.02 | 14.31 |
| medium | 768 | hybrid | 21 | 5.00 (**4.64**†) | 4.64 | 0.786 (**0.714**†) | 13/14 | 211 | 11.74 | 11.95 |
| large | 1024 | fixed | 32 | 5.00 | 4.36 | 0.929 | 14/14 | 1,354 | 9.09 | 10.44 |
| large | 1024 | overlap | 24 | 5.00 | 4.71 | 0.929 | 14/14 | 1,251 | 13.86 | 15.11 |
| large | 1024 | hybrid | 21 | 5.00 | 4.71 | 0.881 | 14/14 | 1,459 | 12.29 | 13.75 |

† corrected for the grader false positive described above.

*Retrieval ms* is the in-run time to embed the query and search, measured while Granite was
loaded on the same CPU. Measured again with the generator idle, one query embeds in **25 ms**
(small), **85 ms** (medium) and **329 ms** (large). That is about 4× lower in absolute terms,
but the large model is ~13× slower than the small one either way.

### Split by query set (context / answer)

| Embedding | Chunking | Direct | Hard |
|---|---|---|---|
| small | fixed | 5.00 / 4.29 | 5.00 / 5.00 |
| small | overlap | 4.29 / 4.29 | 5.00 / 5.00 |
| small | hybrid | 5.00 / 4.43 | 5.00 / 5.00 |
| medium | fixed | 4.71 / 3.71 | 5.00 / 5.00 |
| medium | overlap | 5.00 / 5.00 | 5.00 / 5.00 |
| medium | hybrid | 5.00 / 5.00 | 5.00† / 4.29 |
| large | fixed | 5.00 / 5.00 | 5.00 / 3.71 |
| large | overlap | 5.00 / 5.00 | 5.00 / 4.43 |
| large | hybrid | 5.00 / 5.00 | 5.00 / 4.43 |

**Best configuration:** medium (768d) + overlap, with answer 5.00 (14/14). **Worst:** medium
(768d) + fixed, with answer 4.36, tied with large + fixed on answers and below it on MRR. The best and the worst use
the same embedding model, which is the first sign that chunking moved the answers more than
embedding size did.

**How much a difference means.** One query changing from 5 to 0 moves a configuration's mean by
0.36, and an embedding model's or a strategy's mean (42 queries) by 0.12. Most gaps below are one
to three answers. Read them as tendencies, not rankings.

**Reproducibility.** `run_experiments.py` repeats the 9-configuration grid independently of the
notebook (`results/part2_grid.json`). Across the two runs, 124 of 126 answers are identical word
for word, and one score differs: medium + fixed Q1 abstained in the notebook run (0) and answered
on topic without the price in the script run (1). Greedy decoding with a fixed seed is close to
deterministic on a CPU, but not exactly. One more reason not to read a one-answer gap as a
ranking.

---

## Step 2.3 — Comparing embedding models

Each row averages one embedding model over 3 chunking strategies × 14 queries = 42 queries.

| Embedding | Dim | Context | Answer | Full-mark answers | MRR | Gold-doc recall | Direct ans | Hard ans | Query embed (idle CPU) | Index build |
|---|---|---|---|---|---|---|---|---|---|---|
| small | 384 | 4.88 | **4.67** | 39/42 | 0.909 | 41/42 | 4.33 | 5.00 | **25 ms** | 0.9–1.5 s |
| medium | 768 | 4.95 (4.83†) | **4.67** | 39/42 | 0.829 (0.805†) | 41/42 | 4.57 | 4.76 | 85 ms | 9.5–14.4 s |
| large | 1024 | **5.00** | 4.60 | 38/42 | **0.913** | **42/42** | 5.00 | 4.19 | 329 ms | 21.0–28.8 s |

**How does embedding size affect retrieval quality?** Slightly, in favour of the large model.
It is the only one that never missed the answer's document (42/42), and it has the best MRR
(0.913). Small and medium each missed once: small on Q2 with overlapping chunks, medium on H7
with hybrid chunks. But small's MRR (0.909) is within 0.004 of large's, and medium's is the
lowest. So retrieval quality is not ordered by size either. The 768-d model ranks the answer
lowest of the three.

**How does embedding size affect answer quality?** It doesn't, measurably: 4.67 / 4.67 / 4.60,
which is 39, 39 and 38 full-mark answers out of 42. A one-answer gap is noise at this sample
size. The large model's extra retrieval accuracy did not reach the answers, because its failures
were not retrieval failures: three of its four were H6, where it retrieved the right document
and the question itself was ambiguous (Part 3).

**Did larger embeddings always perform better?** **No.** The large model retrieved slightly
better and answered no better, at **~13× the per-query embedding cost** (329 ms vs 25 ms) and
~20× the index-build time. The first submission's run, with a different generator
(`llama3.2:3b`), reached the same verdict: small 4.79, large 4.71. That is the most robust finding
in this section, because it held across two generation models.

*Why:* eight documents on clearly distinct topics are easy to separate. 384 dimensions already
put "pricing" and "privacy" far apart, so the larger models' extra capacity has little left to
resolve. Larger embeddings should earn their cost on a corpus of many semantically close chunks,
which is the opposite of this one.

---

## Step 2.4 — Comparing chunking strategies

Each row averages one strategy over 3 embedding models × 14 queries.

| Strategy | Chunks | Mean words | Context | Answer | Full-mark answers | MRR | Gold-doc recall | Words in prompt (k=3) | Prompt tokens | Gen s |
|---|---|---|---|---|---|---|---|---|---|---|
| fixed | 32 | 97 | 4.95 | 4.45 | 37/42 | 0.877 | **42/42** | 291 | 506 | **9.5** |
| overlap | 24 | 194 | 4.88 | **4.79** | **40/42** | **0.913** | 41/42 | 578 | 861 | 14.4 |
| hybrid | 21 | 134 | 5.00 (4.88†) | 4.69 | 39/42 | 0.861 (0.837†) | 41/42 | 407 | 710 | 12.7 |

**Which strategy worked better?** It depends on the goal:
* **Final answers:** overlapping paragraphs (4.79, 40/42 full marks, best MRR).
* **Pure retrieval:** fixed-length is the only strategy that always brought back the right
  document (42/42), though one of its chunks missed the answer sentence (Q1, context 3).

Fixed-length gave the **worst answers** (4.45). It was also the weakest strategy for answers in
the first run, so that result holds across both generators.

**Why.** Answer quality rose with the amount of surrounding text each chunk carries:
fixed (291 words in the prompt) **4.45** < hybrid (407) **4.69** < overlap (578) **4.79**.
Several of the failures are Granite picking the wrong figure out of a chunk that *did* contain
the answer:
* Q5: "Pro is sixty per minute and Team six hundred", answered with six hundred.
* Q7: "fourteen day refund" next to "refunds appear within five business days", answered "14
  business days".

A 97-word fixed chunk often holds the fact without the sentence around it that says which plan or
which window the number belongs to. Two adjacent paragraphs carry that sentence along.

Step 3.3 shows the same mechanism from the other side: giving the weakest fixed-length
configuration more context (k=5) fixed every one of its failures.

The hybrid strategy's title prefix ("Plans and Pricing. …") helps retrieval tell documents apart,
but its chunks are smaller than overlap's, so it sits in between.

**Effect on retrieval relevance vs final answers.** On retrieval, chunking barely mattered:
41–42 of 42 right-document retrievals for every strategy. On final answers it mattered more than
anything else in the experiment. The spread between strategies is **0.33**, against **0.07**
between embedding models.

That ordering reversed from the first run (llama3.2: chunking 0.10, embedding 0.31). The honest
reading is that both effects are small enough that the generator decides which one shows. The
part that held in both runs is that fixed-length chunks gave the weakest answers.

**The cost of the winner.** Overlap's better answers are paid for on every request:
* **+70% prompt tokens** (861 vs 506), because every paragraph is stored twice and each chunk is
  twice as wide;
* **+51% generation time** on this CPU (14.4 s vs 9.5 s), because a CPU model reads every prompt
  token before it writes one.

Part 4.1 prices this.

---

## Step 2.5 — Data scaling

The configuration is held fixed at **small + hybrid**, and the index grows from 2 documents to
all 8. Only queries whose answer lies inside the current subset are asked. *Noise* is the share
of retrieved slots that came from a document other than the one holding the answer.

| Docs | Paragraphs | Chunks | Queries | Context | Answer | MRR | Off-document chunks (noise) |
|---|---|---|---|---|---|---|---|
| 2 | 8 | 7 | 2 | 5.00 | 5.00 | 1.000 | 0/6 (0%) |
| 4 | 16 | 12 | 7 | 5.00 | 5.00 | 0.929 | 3/21 (14%) |
| 6 | 24 | 17 | 12 | 5.00 | 5.00 | 0.903 | 13/36 (36%) |
| 8 | 32 | 21 | 14 | 5.00 | 5.00 | 0.917 | 18/42 (43%) |

**Retrieval quality** held at 5.00 throughout: the answer-bearing chunk was always retrieved.
MRR fell from 1.000 to about 0.91, so the answer chunk is pushed down the ranking as the corpus
grows.

**Noise** rose steadily: **0% → 14% → 36% → 43%**. By the full corpus, nearly half of every
retrieved context came from a document that does not hold the answer.

**Answer quality did not move (5.00 at every size).** Noise is a *leading* indicator and
accuracy a *lagging* one. At this scale the generator ignores the irrelevant neighbours. But the
right chunk is already being pushed down the ranking, and with k fixed at 3, every distractor
takes a slot a real result could have used. A system watched only on answer quality looks
healthy until the distractors finally displace the answer.

**Limits:** the 2-document point has only 2 answerable queries, and "larger" here is the full
8-document corpus, not something beyond it. The trend is clear; the exact percentages are not
precise.

---

## Part 3 — Failure analysis

**10 failing rows out of 126.** The notebook's mechanical classifier (Step 3.2 cell) sorts
them by score pattern: 8 generation-side, 1 retrieval, 1 chunking. That classifier can only see
scores. Reading each failure's retrieved chunks, as below, re-attributes them to the causes the
assignment asks about.

### Step 3.1 / 3.2 — The failures, with root causes

**F1. Wrong chunks retrieved: Q2 "How long are notifications kept on the free plan?"
(small + overlap)**
* *Retrieved:* two support chunks ("The Free plan receives best effort support…") and a
  pricing chunk. The privacy document, which holds "The Free plan retains notifications for
  seven days", was not in the top 3. *Answer:* "NOT IN CONTEXT" (context 0, answer 0).
* **Root cause: chunking, made worse by the small embedding model.** The same small model finds
  the privacy chunk with fixed and hybrid chunks, and the medium and large models find it even
  with overlap. Overlap merges the retention paragraph with its neighbour into a ~200-word
  chunk, which dilutes its vector, while the support chunks repeat the query's exact phrase
  "Free plan". The model's abstention was correct given what it was shown.

**F2. Incomplete context: Q1 "How much does the Pro plan cost per month?" (medium + fixed)**
* *Retrieved:* the pricing document's *second* fixed-length chunk (annual billing, student
  discount) and two support chunks. The sentence "The Pro plan costs eight dollars per month"
  is in the pricing document's first chunk, which ranked outside the top 3 (context 3).
* *Answer:* "The context does not provide information on the monthly cost… It only mentions the
  annual cost, which is ninety-six dollars." A correct abstention.
* **Root cause: chunking.** The 120-word budget split the pricing document so that the chunk
  that matched "Pro plan … per month" best was not the one containing the price. Fixed in
  Step 3.3.

**F3. Retrieval miss hidden by the grader: H7 "How many times does a failed webhook get
retried?" (medium + hybrid)**
* *Retrieved:* a support chunk (maintenance and incident reviews "within five business days")
  and two connectors chunks ("A degraded connector is retried on a backoff schedule…"; "PagerDuty
  events arrive through an inbound webhook…"). The architecture document ("Outbound webhooks are
  retried up to five times") was not retrieved by this configuration, though all eight others
  ranked it first. *Answer:* "NOT IN CONTEXT", which is correct.
* **Root cause: embedding model, set up by query formulation.** "failed… retried" and "webhook"
  are exactly the words the connectors document uses about something else. Under this one
  configuration the 768-d model scored that lexical-topic overlap above the actual answer.
* **And a measurement failure.** The grader's accepted answer token "five" matched "five
  business days", so this row was scored context 5 and blamed on generation. Corrected values
  are given in Step 2.2.

**F4. Ambiguous question: H6 "Why would my notifications go silent overnight?" (large + fixed,
overlap and hybrid: 3 rows)**
* *Retrieved:* the filtering document's quiet-hours chunk (rank 1 under fixed, rank 2 under the
  others) next to the pricing document's daily-limit paragraph.
* *Answer (large + fixed):* "…if Unopsis has reached its daily notification limit…". It is on
  topic but never says "quiet hours" (answer 1).
* **Root cause: query formulation.** The question describes a *symptom* rather than naming a
  feature, and the corpus has two real explanations for that symptom: quiet hours, and the daily
  notification limit, which "stops sending push and email delivery for the remainder of the day".
  The model chose a defensible one. The gold answer accepts only "quiet hours", so this is as
  much a narrow test case as a model error.
* Only the large model failed it. Its stronger semantic matching ranked the daily-limit
  paragraph, which is about notifications stopping, at or near the top.

**F5. Hallucinated / wrong figure: Q5 "How many API requests per minute can a Pro account
make?" (small + fixed)**
* *Retrieved:* the right chunk at rank 1: "Pro accounts are limited to sixty requests per minute
  and Team accounts to six hundred requests per minute".
* *Answer:* "A Pro account is limited to six hundred requests per minute." (answer 0,
  contradicting fact.)
* **Root cause: generation.** Retrieval, chunking and the query were all fine. The 2B model, in
  its 4-bit build, attached the Team figure to the Pro plan when both appear in one sentence. The
  same query was answered correctly in the other eight configurations.

**F6. Merged facts and a format slip: Q7 / H1 (small + hybrid, medium + fixed, large + fixed)**
* **Q7 "How long is the refund window on a paid plan?" (small + hybrid)**
  * *Retrieved:* the right chunk at rank 1, containing "a fourteen day refund on any paid plan"
    next to "refunds… appear within five business days".
  * *Answer:* "14 business days.", which merges the two figures (answer 1). Under medium + fixed,
    the model said the window "is not explicitly stated".
* **H1 (large + fixed).** The model wrote "NOT IN CONTEXT. According to the provided context…
  Unopsis offers a fourteen day refund on any paid plan". The fact is right, but it starts with
  the abstention phrase the prompt reserves for "no answer", so it is scored 0.
* **Root cause: generation.** In both cases the answer was in the prompt. The fix is the prompt,
  not retrieval: tell the model to use NOT IN CONTEXT *only* as the whole answer.

**Re-attributed totals (10 rows):**

| Root cause | Rows | Which |
|---|---|---|
| Generation (wrong figure, merged facts, format) | 4 | Q5, Q7 ×2, H1 |
| Query formulation (ambiguous symptom question) | 3 | H6 ×3 |
| Chunking | 2 | Q1 (fixed boundary), Q2 (overlap dilution, with the small model) |
| Embedding model (lexical collision set up by the query) | 1 | H7 |

So 4 of 10 failures are generation errors that no retriever could fix, 3 come from the question
itself, and only 3 from the retrieval stack. Two of those three are chunking.

### Step 3.3 — System improvement

Target: the weakest configuration, **medium (768d) + fixed**. Two fixes, each re-run live on the
identical query set, grader and seed:

| Variant | Context | Answer | MRR | Full-mark answers | Context words in prompt | Prompt tokens |
|---|---|---|---|---|---|---|
| before (k=3, fixed) | 4.86 | 4.36 | 0.821 | 12/14 | 292 | 508 |
| **fix 1: k=5, fixed** | 5.00 | **5.00** | 0.839 | **14/14** | 483 (+65%) | 765 (+51%) |
| fix 2: overlap chunking, k=3 | 5.00 | **5.00** | **0.881** | **14/14** | 577 (+98%) | ~864 (+70%) |

Query by query (notebook, Step 3.3):
* Both fixes repair the same two rows: **Q1** (context 3 → 5, answer 0 → 5: F2's chunk boundary)
  and **Q7** (answer 1 → 5: with more of the pricing document in view, Granite stated "fourteen
  day").
* Neither fix broke any other query; the remaining 12 rows are unchanged at 5/5.

**Why it helped.** Both fixes put more of the right document into the prompt. That repairs a
chunk-boundary miss (Q1) and also gives the generator the surrounding sentence it needs to bind
a number to the right thing (Q7), which is the Step 2.4 mechanism.

**Recommendation: fix 1 (k=5) for this configuration.** It reaches the same 14/14 with fewer
extra prompt tokens (+51% against +70%) and needs no re-index. Overlap chunking ranks the answer
better (MRR 0.881) and is the better *default strategy* (Step 2.4). But on cost it is the more
expensive fix here, because each overlapping chunk is twice as wide. This corrects the first
submission's reasoning, which claimed the chunking fix added no tokens. It adds more than raising
k does.

---

## Part 4 — System design reflection

### Step 4.1 — Cost awareness

The three knobs cost different things, and two of them are paid on every request:

| Factor | When it is paid | Measured in this system |
|---|---|---|
| **top-k** | every request | k=3 → 5: **+51% prompt tokens** (508 → 765). Each retrieved chunk is pasted into every prompt. |
| **Chunk size** | every request | overlap vs fixed at the same k: **+70% prompt tokens** (861 vs 506) and **+51% generation time** (14.4 s vs 9.5 s). |
| **Embedding size** | at index time **and** every request | Index: 31.5–128 KB, built in 0.9–29 s, once. Per query: **25 ms (small) vs 329 ms (large)**, because every query is embedded too. |

**Which matters most: the prompt size, which top-k and chunk size multiply together.** On a
hosted per-token API it is the bill. On our own hardware it is the latency, because generation
is ~12 s of a ~13 s request on this CPU and grows with every prompt token.

Embedding size is *not* a one-off cost, contrary to the first submission. The query is embedded
on every request, and the large model is 13× slower at it. At 30,000 queries a day (Step 4.3),
that is 2.7 CPU-hours a day for the large model against 0.2 for the small one, for no measured
gain in answers (Step 2.3). It is still the smallest of the three in absolute terms (0.33 s
against ~12 s of generation), which is why it ranks third.

### Step 4.2 — RAG vs alternatives

| Approach | When to use | Evidence from our own work |
|---|---|---|
| **RAG** | Facts change often; answers must be traceable to a source; the corpus is large relative to what a prompt can hold | Here RAG answered 4.36–5.00 out of 5 with ~500–860 prompt tokens per question. Editing a pricing document changes the next answer, with no retraining. |
| **Fine-tuning** | The *format*, tone or vocabulary must change; the task is stable; prompt cost must be minimised | In **A7 Part 2** (notebook 3) we fine-tuned our from-scratch character-level SLM on the knowledge base. It was the *only* condition that got facts into answers (7.3/10 on Q1, where RAG and the baseline both scored 2.0). But it also mixed facts up: asked what membership costs, it answered "far dorms costs five dollars" (the answer is ten). And every price change would mean retraining. |
| **Pure prompting** | The whole knowledge fits comfortably in the context window and rarely changes | We tested it on this corpus with Granite. The whole corpus is **4,184 tokens**, and with Ollama's default context only **2,050** reached the model: half the corpus was **silently truncated**. With the context raised to fit it, one answer took **93.5 s** against ~12 s with RAG, using 5–8× the prompt tokens. |

**Conclusions from our own runs.**

A7 Part 2's RAG failed only because that model had a 32-character context window, so the
retrieved fact never fit. Its own conclusion was "RAG, but on a model with a usable context
window". A8 is that experiment, and RAG works here.

Even at 3,093 words, pure prompting is not the free baseline it looks like. It needs the context
window configured explicitly, or it fails without an error, and it costs several times more per
question.

The approaches are complementary: fine-tune for *how* to answer, and retrieve for *what is true*.
Step 2.5's rising noise shows where retrieval earns its place as the corpus grows.

### Step 4.3 — System design for 10,000 users/day

**Load.** We assume 3 questions per user per day, which gives **30,000 queries/day**: 0.35/s on
average, and about 1.7/s at a 5× daytime peak.

**Where the time goes, measured.**
* Retrieval is 25 ms with the small model.
* Generation is 6–26 s per answer on this laptop CPU (mean 12.2 s), one request at a time.

At peak that would take ~20 CPU generation workers running in parallel, so generation is the
component to engineer. The vector store is not.

```
                          ┌──────────────────────────────────────────┐
                          │             INGESTION (offline)          │
                          │  documents → chunker → embedding model   │
                          │                    ↓                     │
                          │          vector store (upsert)           │
                          └──────────────────────────────────────────┘
                                             ↑ on document edit
  ┌──────┐   query    ┌───────────┐  vector  ┌──────────────┐  top-k   ┌─────────────┐
  │ User │ ─────────► │   API     │ ───────► │ Vector store │ ───────► │   Prompt    │
  └──────┘            │  (REST)   │          │ (exact→ANN)  │  chunks  │  assembly   │
      ▲               └───────────┘          └──────────────┘          └─────────────┘
      │                     │                                                │
      │                     ▼ cache lookup                                   ▼
      │              ┌─────────────┐                                  ┌───────────────┐
      │              │ query cache │                                  │  LLM server   │
      │              │   (Redis)   │                                  │ Granite-3.3-2B│
      │              └─────────────┘                                  │  (GPU, vLLM)  │
      │                     │ hit                                     └───────────────┘
      └─────────────────────┴─────────────── response ◄────────────────────────┘
```

User → Query → Embedding → Vector store → Retrieved context → LLM → Response, with a cache in
front and ingestion kept off the request path.

**What we would optimise, in order:**
1. **Serve generation from a GPU with batching (e.g. vLLM).** A6 measured Granite-3.3-2B at
   ~1.7 s per message on a single T4, and batching serves many requests at once, so one GPU
   covers the 1.7/s peak that would need ~20 CPU workers.
2. **Cache answers.** Support questions repeat ("how much is Pro"). Key the cache on the
   normalised query plus the retrieved chunk IDs, so editing a document invalidates only the
   answers that used it. A hit skips generation, the dominant cost, entirely.
3. **Keep the prompt small.** Top-k and chunk width multiply prompt tokens (Step 4.1). Use k=3
   by default, and raise k, or switch to wider chunks, only for the query types that need it
   (Step 3.3 shows when it helps).
4. **Keep the small embedding model, resident in memory.** It answered as well as the large one
   (Step 2.3) at 1/13 of the per-query cost. Load it once per process, never per request.
5. **Move the vector store from exact NumPy search to pgvector or FAISS past ~10⁵ chunks.**
   Below that, exact search is faster and has no approximation error.
6. **Monitor retrieval noise, not just answer quality.** Step 2.5 shows noise rises well before
   answers degrade.
7. **Fix the prompt's abstention rule:** NOT IN CONTEXT must be the *whole* answer (failure F6).

**What we would not do:** buy a bigger embedding model. Part 3 put the failures in generation
and in the questions themselves, not in the embeddings.

---

## Summary

1. **A bigger embedding model bought slightly better retrieval, not better answers.**
   * Large never missed the right document (42/42), but answered 4.60 against 4.67 for small and
     medium.
   * It costs 13× more per query.
   * The same verdict came out of both generator runs.
2. **Answers tracked how much context each chunk carried.** Fixed-length (4.45) < hybrid (4.69)
   < overlap (4.79). Raising k to 5 fixed the weakest configuration completely (14/14). More
   context costs prompt tokens and latency on every request (+51–70%).
3. **Under Granite, chunking moved answers ~5× more than embedding size** (spread 0.33 vs 0.07).
   That ordering reversed between generators, so both effects are small, and only "fixed-length
   is weakest for answers" held in both runs.
4. **The failures were mostly not retrieval failures.**
   * 4 of 10 were generation errors with the answer in the prompt.
   * 3 came from an ambiguous question.
   * Only 3 came from the retrieval stack: 2 chunking, 1 embedding.
   * Reading the chunks also exposed two grader artifacts, which are reported and corrected above.
5. **Noise leads, accuracy lags.** Off-document retrievals rose 0% → 43% as the corpus grew while
   answers stayed at 5.00. That is the metric to monitor.
6. **Pure prompting is not free even for a 3,093-word corpus.** It was silently truncated at
   Ollama's default context, and 7–8× slower once configured to fit.
