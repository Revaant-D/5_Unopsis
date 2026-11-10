"""
Run every A8 experiment and write results/*.json.

The notebook runs these same functions live rather than reading the JSON, so the saved files
are a record and a cross-check, not the source of the notebook's tables. (A7 taught this the
hard way: a notebook whose cells print one set of numbers while its prose quotes a stale file
is worse than a notebook with no prose at all.)
"""
import json, pathlib, time
from sentence_transformers import SentenceTransformer
import ragkit as rk

OUT = pathlib.Path(__file__).parent / "results"
OUT.mkdir(exist_ok=True)
K = 3


def load_embedders():
    """Loaded once and reused; model load time is reported separately from query latency."""
    out = {}
    for size, name, dim in rk.EMBEDDERS:
        t0 = time.perf_counter()
        out[size] = {"name": name, "dim": dim, "model": SentenceTransformer(name),
                     "load_sec": round(time.perf_counter() - t0, 2)}
    return out


def part2_grid(embedders, docs, k=K):
    """3 embedding models x 3 chunking strategies = 9 configurations."""
    chunksets = {s: fn(docs) for s, fn in rk.STRATEGIES.items()}
    grid = []
    for size in ("small", "medium", "large"):
        e = embedders[size]
        for strat in ("fixed", "overlap", "hybrid"):
            chunks = chunksets[strat]
            store = rk.VectorStore(e["model"], chunks)
            rows = rk.run_config(store, k=k)
            grid.append({
                "embed_size": size, "embed_model": e["name"], "dim": store.dim,
                "strategy": strat, "n_chunks": len(chunks),
                "mean_chunk_words": round(sum(c["words"] for c in chunks) / len(chunks), 1),
                "index_sec": round(store.index_sec, 2), "model_load_sec": e["load_sec"],
                "rows": rows,
                "mean_context_quality": round(sum(r["context_quality"] for r in rows) / len(rows), 2),
                "mean_answer_quality": round(sum(r["answer_quality"] for r in rows) / len(rows), 2),
                "mean_total_latency": round(sum(r["latency"]["total"] for r in rows) / len(rows), 2),
                "mean_retrieval_latency": round(sum(r["latency"]["embed_query"] + r["latency"]["search"]
                                                    for r in rows) / len(rows), 4),
                "gold_doc_recall": sum(1 for r in rows if r["gold_doc_retrieved"]),
                "n_queries": len(rows),
                # Reported per difficulty because the two sets behave completely differently and
                # a single average hides that. See the comment on HARD_QUERIES in ragkit.py.
                "by_difficulty": {
                    d: {
                        "n": len(sub),
                        "context_quality": round(sum(r["context_quality"] for r in sub) / len(sub), 2),
                        "answer_quality": round(sum(r["answer_quality"] for r in sub) / len(sub), 2),
                        "gold_doc_recall": sum(1 for r in sub if r["gold_doc_retrieved"]),
                        "answer_at_rank_1": sum(1 for r in sub if r["answer_rank"] == 1),
                        "mrr": round(sum(1 / r["answer_rank"] for r in sub if r["answer_rank"]) / len(sub), 3),
                    }
                    for d in ("direct", "hard")
                    if (sub := [r for r in rows if r["difficulty"] == d])
                },
                "mrr": round(sum(1 / r["answer_rank"] for r in rows if r["answer_rank"]) / len(rows), 3),
            })
            c = grid[-1]
            bd = c["by_difficulty"]
            print(f"  {size:<7} {strat:<8} chunks {len(chunks):>3} dim {store.dim:>4} | "
                  f"ALL ctx {c['mean_context_quality']:.2f} ans {c['mean_answer_quality']:.2f} "
                  f"mrr {c['mrr']:.3f} | "
                  f"direct {bd['direct']['context_quality']:.2f}/{bd['direct']['answer_quality']:.2f} "
                  f"hard {bd['hard']['context_quality']:.2f}/{bd['hard']['answer_quality']:.2f} | "
                  f"{c['mean_total_latency']:.2f}s/q", flush=True)
    return grid


def part25_scaling(embedders, docs, size="small", strategy="hybrid", k=K):
    """Step 2.5: hold the configuration fixed and grow the index."""
    e, fn, out = embedders[size], rk.STRATEGIES[strategy], []
    for n in (2, 4, 6, 8):
        subset = docs[:n]
        chunks = fn(subset)
        store = rk.VectorStore(e["model"], chunks)
        # only questions whose answer is inside this subset can be answered at all
        answerable = [q for q in rk.QUERIES if q["gold_doc"] in {d["id"] for d in subset}]
        rows = rk.run_config(store, queries=answerable, k=k) if answerable else []
        rec = {
            "n_docs": n, "n_paragraphs": sum(len(d["paragraphs"]) for d in subset),
            "n_chunks": len(chunks), "answerable_queries": [q["id"] for q in answerable],
            "rows": rows,
            "mean_context_quality": round(sum(r["context_quality"] for r in rows) / len(rows), 2) if rows else None,
            "mean_answer_quality": round(sum(r["answer_quality"] for r in rows) / len(rows), 2) if rows else None,
            "mean_answer_rank": (round(sum(r["answer_rank"] for r in rows if r["answer_rank"]) /
                                       max(1, sum(1 for r in rows if r["answer_rank"])), 2)),
            "distractor_slots": sum(len(r["retrieved"]) - (1 if r["answer_rank"] else 0) for r in rows),
            "off_doc_chunks_retrieved": sum(1 for r in rows for h in r["retrieved"]
                                            if h["doc_id"] != r["gold_doc"]),
            "retrieved_slots": sum(len(r["retrieved"]) for r in rows),
        }
        out.append(rec)
        print(f"  {n} docs ({rec['n_paragraphs']} paras, {rec['n_chunks']} chunks) | "
              f"queries {len(answerable)} | ctx {rec['mean_context_quality']} "
              f"ans {rec['mean_answer_quality']} | off-doc chunks "
              f"{rec['off_doc_chunks_retrieved']}/{rec['retrieved_slots']}", flush=True)
    return out


if __name__ == "__main__":
    docs = rk.load_documents()
    print(f"corpus: {len(docs)} documents, {sum(len(d['paragraphs']) for d in docs)} paragraphs, "
          f"{sum(len(p.split()) for d in docs for p in d['paragraphs'])} words")
    print(f"generation model: {rk.GEN_MODEL} (held constant)\n")
    embedders = load_embedders()
    print("PART 2.2 - the 9 configurations")
    grid = part2_grid(embedders, docs)
    (OUT / "part2_grid.json").write_text(json.dumps(grid, indent=2))
    print("\nPART 2.5 - data scaling")
    scaling = part25_scaling(embedders, docs)
    (OUT / "part25_scaling.json").write_text(json.dumps(scaling, indent=2))
    print(f"\nwrote {OUT}/part2_grid.json and part25_scaling.json")
