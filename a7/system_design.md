# Unopsis — Multi-Model System Design (Assignment 7)

**Team 5 · INFO 490 MG · Fall 2026**
Experiments, benchmark data and simulations: [`multi_model_system.ipynb`](multi_model_system.ipynb)
(all numbers below come from that notebook, run on a Google Colab Tesla T4).

---

## 1. The system in one paragraph

Unopsis reads a user's messages (Gmail, Outlook, Slack, Discord, WhatsApp) and writes one
short brief twice a day. Every incoming message needs **cheap, high-volume** work: triage into a
lane (classification), pulling out who/what/when (structured extraction), and an urgency score
(prediction). Twice a day per user it also needs **low-volume, quality-sensitive** work:
summarising threads and drafting replies (summarization, text generation). The two workloads
differ by ~75× in volume, so no single model is the right answer for both. That observation
drives every decision below.

## 2. Architecture

```
                         incoming message (≈150 / user / day)
                                        │
                              ┌─────────▼──────────┐
                              │   preprocessing    │ strip HTML, redact e-mail/phone/links,
                              │   + guardrails     │ prompt-injection screen, 2,000-char cap
                              └─────────┬──────────┘
                              ┌─────────▼──────────┐
                              │      ROUTER        │ inputs: prompt type, input length,
                              │                    │ model confidence, GPU queue depth,
                              │                    │ API health, daily API spend
                              └──┬──────┬──────┬───┘
                 ┌───────────────┘      │      └─────────────────┐
        ┌────────▼───────┐    ┌─────────▼────────┐    ┌──────────▼───────────┐
        │ Tier 0: rules  │    │ Tier 1: small    │    │ Tier 2: medium local │
        │ keyword lanes  │    │ SmolLM2-1.7B     │    │ Qwen2.5-7B (4-bit)   │
        │ ~0 ms, $0      │    │ 0.58 s, 9.32/10  │    │ 1.38 s, 9.91/10      │
        └────────────────┘    └──────────────────┘    └──────────────────────┘
                                                      ┌──────────────────────┐
                                                      │ Tier 3: HF Inference │
                                                      │ Llama-3.3-70B (API)  │
                                                      │ hard / long inputs   │
                                                      └──────────────────────┘
                                        │
                     JSON validated → stored on the Brief → shown to the user
              (invalid output → escalate one tier; nothing is ever sent on the user's behalf)
```

Tiers 1–2 are the models our benchmark picked (Section 3). The router sends each request to the
cheapest tier that is good enough, and moves work between tiers when conditions change (Section 5).

---

## 3. Benchmark results (Part 1)

15 models × 25 prompts (5 prompt types × 5 prompts) = **375 runs**, greedy decoding, scored
1–10 on instruction adherence, accuracy, clarity and structure (self-evaluation score = mean).

### 3.1 By category

| Category | Mean score | Tokens/sec | Latency (s) | Best model in category |
|---|---|---|---|---|
| 1 Ultra-Light (< 1B) | 8.45 | 22.80 | 1.22 | Qwen2.5-0.5B-Instruct (9.38) |
| 2 Small (1–2B) | 9.47 | **27.68** | **0.84** | Qwen3-1.7B (9.74) |
| 3 Medium (2–4B) | 9.65 | 17.59 | 1.42 | Granite-3.3-2B-Instruct (9.76) |
| 4 Large (7–9B) | **9.69** | 11.25 | 1.75 | **Qwen2.5-7B-Instruct (9.91)** |
| 5 Very Large (12–15B) | 9.43 | 8.38 | 2.43 | Qwen2.5-14B-Instruct (9.77) |

### 3.2 By category × prompt type

| Category | Classification | Extraction | Generation | Prediction | Summarization |
|---|---|---|---|---|---|
| Ultra-Light | 7.63 | 8.60 | 9.43 | 7.55 | 9.02 |
| Small | **9.53** | 9.25 | 9.60 | 9.55 | 9.43 |
| Medium | 9.52 | **9.90** | 9.85 | 9.25 | 9.75 |
| Large | 9.20 | 9.85 | **9.93** | **9.65** | **9.80** |
| Very Large | 9.27 | 9.30 | 9.57 | 9.35 | 9.68 |

### 3.3 What the benchmark says

* **Best category: Large (7–9B), 9.69**, but Medium (9.65) and Small (9.47) are close behind,
  and the best single model, **Qwen2.5-7B-Instruct (9.91)**, is a 7B model, not a 14B one.
* **Bigger was not always better.** There were 8 cases where a larger model scored lower than
  the next-smaller one. The Very Large category (9.43) scored *below* Medium and Large: Phi-4 (14.7B)
  scored 8.90, under several 1–3B models, mostly by adding text around its JSON. For
  **classification**, the Small category (9.53) beat both Large (9.20) and Very Large (9.27).
  Size helped most on **generation and summarization** (Large 9.93 / 9.80), which matches the
  intuition that open-ended writing benefits from capacity while short labelling tasks saturate early.
* **Below 1B quality drops sharply** (8.45, and SmolLM2-360M at 7.13): these models break the JSON
  format and get urgency wrong (prediction 7.55).
* **Best speed/quality balance: SmolLM2-1.7B-Instruct.** It scored 9.32, the fastest of all 15 at
  38.71 tokens/s and 0.58 s per answer, using 3.5 GB. **Granite-3.3-2B** (9.76 at 16.9 tok/s) is
  the best choice when quality matters slightly more than speed.
* Caveat: scores cluster between 9 and 10 because our rubric checks objective things (format,
  required facts, length). It separates broken from working outputs well; it separates
  "good" from "excellent" prose less well, which understates the advantage of large models on
  generation.

**Model selection:** Tier 1 = SmolLM2-1.7B (bulk triage), Tier 2 = Qwen2.5-7B (quality, 6 GB in
4-bit), Tier 0 rules for overload, Tier 3 a hosted 70B model for the hardest inputs.

---

## 4. Cost analysis (Part 2)

### 4.1 Token load

| Request | Per user per day | Input tokens | Output tokens |
|---|---|---|---|
| Triage a message (classification + extraction + prediction) | 150 | 430 | 35 |
| Write a brief (summarization + generation) | 2 | 950 | 300 |
| **Per user per day** | 152 requests | **66,400** | **5,850** |

**Average tokens per user = 72,250 per day (≈ 475 per request).**

| Traffic category | Daily active users | Total daily token load |
|---|---|---|
| Prototype | 1,000 | 72.25 million |
| Early Startup | 10,000 | 722.5 million |
| Growing Product | 100,000 | 7.2 billion |
| Large Platform | 1,000,000 | 72.3 billion |
| Mass Consumer App | 10,000,000 | 722.5 billion |
| Global Platform | 100,000,000 | 7.2 trillion |

### 4.2 Assumptions

* **Local machine:** AWS g5.4xlarge, 16 vCPU, 64 GB RAM, 1× A10G 24 GB, ≈ $1.62/hour = **$38.98/day**
  (approximate on-demand rate).
* **Machine capacity:** measured single-request tokens/sec × 8 concurrent requests × 86,400 s ×
  50% average utilisation (headroom for the 8am peak). Output tokens are the bottleneck.
* **Hugging Face API** (Inference Providers, lowest listed provider rate, Oct 2026):
  `Llama-3.1-8B-Instruct` $0.02 / $0.05 per 1M input/output tokens as the comparable model for the
  < 1B to 9B categories; `Qwen2.5-Coder-32B-Instruct` $0.06 / $0.20 for the 12–15B category.
  Plus our own app servers (t3.medium, ≈ $1/day each, one per 250,000 users).

### 4.3 Local vs API, $ per day (mean of the 3 models in each category)

| Category | | Prototype | Early Startup | Growing | Large | Mass | Global |
|---|---|---|---|---|---|---|---|
| Ultra-Light | local | 38.98 | 311.81 | 3,053 | 30,388 | 303,701 | 3,036,737 |
| | API | **2.62** | **17.20** | **163** | **1,624** | **16,245** | **162,449** |
| Small | local | 38.98 | 285.82 | 2,572 | 25,659 | 256,423 | 2,563,997 |
| | API | **2.62** | **17.20** | **163** | **1,624** | **16,245** | **162,449** |
| Medium | local | 51.97 | 389.76 | 3,781 | 37,742 | 377,340 | 3,773,189 |
| | API | **2.62** | **17.20** | **163** | **1,624** | **16,245** | **162,449** |
| Large | local | 77.95 | 610.62 | 5,924 | 59,140 | 591,188 | 5,911,711 |
| | API | **2.62** | **17.20** | **163** | **1,624** | **16,245** | **162,449** |
| Very Large | local | 103.94 | 805.50 | 7,938 | 79,238 | 792,174 | 7,921,586 |
| | API | **6.15** | **52.54** | **516** | **5,158** | **51,580** | **515,799** |

**Local hosting was cheaper for 0 of 15 models at all 6 traffic levels.** At scale the API is
about **16× cheaper** for Small models, 19× for Ultra-Light, 23× for Medium, 36× for Large and 15× for
Very Large. Both costs grow linearly with users, so the gap does not close by itself as traffic grows.

### 4.4 Why, and where the break-even is

* **API:** one user costs 66,400 × $0.02/M + 5,850 × $0.05/M = **$0.0016 per day**.
* **Local:** our fastest model (SmolLM2-1.7B, 38.7 tok/s) serves ≈ 2,290 users per machine, which is
  **$0.017 per user per day**, about 10× the API.
* **Break-even:** a $38.98/day machine must serve 38.98 ÷ 0.0016 ≈ **24,000 users**, which means
  generating **≈ 1,630 output tokens per second, around the clock**. Our best measured
  throughput is 38.7 tok/s per request × 8 concurrent × 50% utilisation ≈ 155 tok/s on average,
  about **10× short**.
  For the 12–15B category (dearer API) the break-even is ≈ 510 tok/s; we reach ≈ 30.

The gap comes from how we serve, not only from the models. Our numbers are Hugging Face
`transformers.generate()` on a T4, a handful of requests at a time. Hosted providers run
continuous-batching servers (vLLM, TGI) that keep a GPU full with dozens of requests and share the
cost across many customers, which is why an 8B model can be priced at a few cents per million tokens.

### 4.5 Answers

**At what scale is local hosting cheaper?** Under our measured throughput: **at none of the six
scales.** Local only becomes cheaper once a machine sustains about 1,630 output tokens/s for 1–9B
models, or ≈ 510 tok/s for 12–15B. That is a property of the serving stack, not of the user count.
Realistically that requires a batched inference server at high, steady utilisation, so the
earliest scale where it is worth testing is the **Large Platform (1M DAU, ≈ $1,600/day ≈
$49,000/month of API spend)**, where the savings could pay for the engineering effort.

**At what scale is API usage cheaper?** **At every scale we modelled, by 15–36×.** It is
especially clear below 100,000 DAU. At 1,000 users the API costs $2.62/day against $38.98 for a
single machine that would sit mostly idle, and the API also needs no GPU operations work.

**When would we switch our architecture?** We start API-first with local fallback, and would move
bulk triage to self-hosted GPUs when **all** of these are true:
1. We pass ~1M DAU, so API spend is in the tens of thousands of dollars per month.
2. A benchmark of our triage model on a batched server (vLLM) on the target GPU shows sustained
   throughput above the break-even (> 1,630 tok/s per $1.62/h machine), or reserved/spot pricing
   lowers the machine cost enough to move the break-even within reach.
3. Traffic is steady enough to keep GPUs above ~50% utilisation (the 8am/4:30pm brief peaks are
   predictable, which helps).

We would also self-host earlier, regardless of cost, if **privacy or compliance** required that message
bodies never leave our infrastructure, or if API **rate limits or price changes** made the provider
unreliable. Brief writing (2 requests per user per day, quality-sensitive) stays on the API in every case.

---

## 5. Routing design (Part 3)

### 5.1 Five scenarios (Step 3.1)

| # | Scenario | Description in Unopsis terms |
|---|---|---|
| 1 | **Normal operation** | Messages trickle in all day; mostly short, simple triage |
| 2 | **8am brief rush (peak)** | Every user's morning brief is generated in the same few minutes: a predictable spike in summarization/generation |
| 3 | **Cost optimisation** | The daily API budget is nearly used up (or a free-tier quota is reached) |
| 4 | **System overload** | The local GPU queue is full (spike in incoming mail, a machine down) and latency is climbing |
| 5 | **API outage** | Hugging Face / the provider returns errors or times out |

### 5.2 Strategies (Step 3.2)

Routing conditions used: **prompt type**, **input length** (> 600 tokens = long thread), **model
confidence** (valid JSON + agreement; below 0.6 = low), **GPU queue depth**, **API health**,
**daily API spend**.

| Scenario | Routing strategy | Local models used | Hugging Face model used | Expected benefit |
|---|---|---|---|---|
| Normal operation | Short triage → small; low-confidence or medium-length → medium; long threads and briefs → API | SmolLM2-1.7B, Qwen2.5-7B | Llama-3.3-70B-Instruct (long inputs only) | Most traffic answered locally and fast; the API only where it adds quality |
| 8am brief rush | All triage → small model; only brief writing (summarization + generation) → API | SmolLM2-1.7B | Llama-3.3-70B-Instruct | Local GPU stays free for the triage flood; the peak of writing work goes to elastic API capacity |
| Cost optimisation | No API calls: easy → small, hard → medium local | SmolLM2-1.7B, Qwen2.5-7B | none | API spend drops to $0 for the rest of the day |
| System overload | Classification → keyword rules; other triage → small; hard requests → API (shed load off the GPU) | SmolLM2-1.7B + rules | Llama-3.3-70B-Instruct | Queue drains, latency stays bounded, nothing is dropped |
| API outage | Everything local: easy → small, hard → medium; template writer for briefs if needed | SmolLM2-1.7B, Qwen2.5-7B | none (circuit breaker open) | The product keeps working; quality degrades gracefully instead of failing |

### 5.3 Evaluation (Step 3.3)

Simulated in the notebook over 10,000 requests (95% triage, 5% brief writing), using our
**measured** latency and scores for the local models. The API tier is assumed at 1.2 s latency and a
quality score of 10 (slightly above our best local model), priced at $0.135/$0.40 per 1M tokens.

| Scenario | Avg latency (s) | Avg quality (1–10) | API cost per 10k requests | Rules / small / medium / API |
|---|---|---|---|---|
| Normal operation | 1.08 | 9.73 | $0.27 | 0 / 33 / 48 / 19 % |
| 8am brief rush | **0.61** | 9.35 | $0.09 | 0 / 95 / 0 / 5 % |
| Cost optimisation | 0.74 | 9.44 | **$0.00** | 0 / 80 / 20 / 0 % |
| System overload | **0.46** | 8.06 | $0.28 | 42 / 38 / 0 / 20 % |
| API outage | 0.74 | 9.44 | $0.00 | 0 / 80 / 20 / 0 % |
| *Baseline: all to API* | *1.20* | *10.00* | *$0.75* | *0 / 0 / 0 / 100 %* |

**How it improves latency.** The small model answers in 0.58 s against an assumed 1.2 s for an API
round trip, so any request it can handle gets faster. In the brief rush, 95% of requests go to the
small model and average latency falls from 1.20 s to **0.61 s (−49%)**. Under overload, 42% of
requests go to the keyword rules (milliseconds), giving the lowest latency of all at **0.46 s
(−62%)**, at exactly the moment the GPU queue would otherwise make every request slow. Normal
operation improves less (1.08 s, −10%) because it deliberately sends 48% of traffic to the slower
but stronger 7B model.

**How it reduces cost.** Only requests that need a large model are paid for. API spend per 10,000
requests falls from $0.75 to **$0.27 in normal operation (−64%)** and to **$0.09 during the rush
(−88%)**, and to zero in the cost-saving and outage modes. Two design choices compound this. The API
receives one short triaged line per message instead of raw bodies, so the prompts are shorter. And
the high-volume work (triage, 95% of requests) is exactly the work small models do well
(classification 9.53 for Small vs 9.20 for Large).

**How it maintains quality.**
* **Matching model to task:** our benchmark shows small models are as good as large ones on
  classification and extraction, so routing those to Tier 1 costs little quality.
  Summarization and generation, where size helps, go to Tier 2 or the API.
* **Confidence escalation:** an answer with invalid JSON or low confidence is retried one tier up,
  so a small model's failures are corrected instead of shown.
* **Graceful degradation:** quality stays ≥ 9.35 in every scenario except overload (8.06). There we
  deliberately accept keyword-rule triage for classification to keep the system responsive. The
  router switches back as soon as the queue drains.
* **Measured cost of routing:** normal operation keeps **9.73 of a possible 10** (−2.7%) while
  cutting API cost by 64%.

**Limitations of the simulation.** API latency and quality are assumptions rather than
measurements. The request mix is synthetic but shaped like Unopsis traffic, and "confidence" is
simulated rather than computed from real model outputs. A production version would log real
confidence and latency per tier and tune the thresholds (600 tokens, 0.6 confidence) from that data.

---

## 6. Final recommendation

1. **Now (prototype → growing product):** API-first for brief writing; small local model
   (SmolLM2-1.7B or Granite-2B) for triage where we already have a machine (development, the
   instructor's laptop), with the cheap hosted 8B model as the production triage path. Keyword
   rules are always the last fallback.
2. **Run the router from day one.** It is cheap to build, and it is what lets us change providers,
   survive outages and control spend without changing the product.
3. **Re-evaluate self-hosting at ~1M DAU**, with a batched-server throughput test against the
   1,630 tok/s break-even. Move bulk triage local only if that test passes. Briefs stay on the API.
