# A8 — Retrieval-Augmented Generation with Multiple Embedding Models

A RAG pipeline over an eight-document knowledge base, evaluated across **3 embedding models ×
3 chunking strategies = 9 configurations**, using a single generation model held constant
throughout.

| Component | Choice | Why |
|---|---|---|
| Generation model | `granite3.3:2b` via Ollama (IBM Granite-3.3-2B-Instruct) | Our team's pick in A6 (0.692 lane accuracy, best below 4B, tied with the larger Phi-4-mini) and A7 Part 1 (9.76/10, 2nd of 15, best in the Medium 2–4B band), and the model the Unopsis app runs. Ollama serves a 4-bit (Q4_K_M) build of the same weights A6/A7 ran in full precision. Used for **every** configuration — only the embedding model and chunking strategy vary. |
| Small embedding | `sentence-transformers/all-MiniLM-L6-v2` (384-dim) | |
| Medium embedding | `sentence-transformers/all-mpnet-base-v2` (768-dim) | |
| Large embedding | `BAAI/bge-large-en-v1.5` (1024-dim) | |
| Vector store | normalised NumPy matrix, exact cosine search | At 21–32 chunks an exact dot product is faster than any index and has no recall penalty, so there is no approximation to report. |

## Files

| File | |
|---|---|
| `rag_system.ipynb` | the full implementation and every experiment, executed end-to-end |
| `rag_analysis.md` | evaluation tables, embedding and chunking comparisons, failure analysis, system design |
| `ragkit.py` | the pipeline: corpus loading, the three chunking strategies, the vector store, retrieval, prompt construction, generation, and the grading rubric |
| `run_experiments.py` | drives the 9-configuration grid and the data-scaling experiment, writing `results/*.json` |
| `corpus/` | the knowledge base: 8 documents, 32 paragraphs, 3,093 words |
| `results/` | saved experiment output: `notebook_run.json` is the run the notebook and `rag_analysis.md` report; `part2_grid.json` and `part25_scaling.json` are an independent re-run by `run_experiments.py` (124/126 answers identical, see `rag_analysis.md`) |
| `requirements.txt` | pinned Python dependencies |

## Setup

```bash
python -m pip install -r requirements.txt
```

Then install **Ollama** (not a pip package) from <https://ollama.com> and pull the generation
model:

```bash
ollama pull granite3.3:2b
ollama serve                      # usually already running as a background service
```

Confirm it answers before running the notebook:

```bash
curl -s http://localhost:11434/api/generate \
  -d '{"model":"granite3.3:2b","prompt":"say ready","stream":false}'
```

The three embedding models download from Hugging Face on first use, about 2.9 GB in total and
a few minutes on a normal connection. They are cached afterwards.

On macOS, if the kernel dies while loading `sentence-transformers`:

```bash
export KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1
```

## Running

```bash
jupyter notebook rag_system.ipynb        # then Run All
```

The notebook runs every experiment live rather than loading saved results, so its tables are
always produced by the code above them. It makes ~190 generation calls (9 configurations × 14
queries, plus the scaling sweep and the two Step 3.3 fixes), and almost all of the run time is
generation. **On a laptop CPU a full run takes about 45 minutes** (~12 s per answer for Granite
on a 6-core CPU); with a GPU it is a few minutes. To run it headless:

```bash
jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=1800 rag_system.ipynb
```

To run the grid outside the notebook:

```bash
python run_experiments.py
```

All paths are relative to the project root. Nothing refers to a machine-specific location, and
no API keys or credentials are required — both the embedding models and the generation model
run locally.

## A note on the test queries

There are two query sets. The **direct** set (Q1–Q7) phrases questions the way the corpus does.
The **hard** set (H1–H7) uses the wording a real user would reach for, and each query competes
with a near neighbour elsewhere in the corpus. The hard set was written after the direct set
saturated in our first runs. With Granite, both sets produce failures, of different kinds:
* on the direct set, the model picks the wrong figure out of a correct chunk;
* on the hard set, the failures come from ambiguous wording and retrieval collisions.

`rag_analysis.md` Part 3 diagnoses each one.

## About this version (resubmission)

The first submission generated with `llama3.2:3b`, which is not one of the models our team
benchmarked in A6/A7. This version uses **Granite-3.3-2B-Instruct**, our A6/A7 pick, for every
experiment, and re-runs everything end to end. The retrieval-side results are unchanged, because
they do not depend on the generator. All answer-side results, failures and conclusions come from
the new run. The notebook also now prints the retrieved chunks for all nine configurations and at
least three full failure cases.
