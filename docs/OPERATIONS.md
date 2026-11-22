# Model selection, token efficiency and cost: operational readiness

This page asks what it would take to run `scopeeval`, or any similar agent workload, as a routine, budgeted operation rather than a one-off experiment. It covers:
- choosing a model for each role;
- where the tokens and the money go;
- what to observe;
- which optimisations to apply, in what order.

The numbers come from this repository's own runs, mainly the [Claude Haiku 5.5 secondary analysis](RESULTS_HAIKU.md): 1,680 episodes and 4,888 requests, with every request metered. Prices are the list prices in [`src/scopeeval/pricing.py`](../src/scopeeval/pricing.py), as published in November 2026. Check current prices before relying on any dollar figure.

This is an independent, personal research project. Nothing here describes any employer's systems.

## Contents

1. [The short version](#1-the-short-version)
2. [How an agent episode is billed](#2-how-an-agent-episode-is-billed)
3. [Model selection](#3-model-selection)
4. [Token efficiency](#4-token-efficiency)
5. [Use AI to build deterministic components](#5-use-ai-to-build-deterministic-components)
6. [Observability](#6-observability)
7. [Operational readiness checklist](#7-operational-readiness-checklist)
8. [Further optimisations for this project](#8-further-optimisations-for-this-project)

## 1. The short version

- **Judge cost per completed task, not price per token.** Haiku 5.5 is 40 times cheaper per token than Opus 5.5, but was 28 times cheaper per episode on the same 16-episode check, because it wrote more output.
- **Output tokens are the bill.** They were 73% of Haiku's cost and would be about 78% at Opus or Sonnet prices. On Claude 5-generation models they include the model's thinking, which you pay for even though it is not shown.
- **Prompt caching is the largest free lever.** 93% of input tokens were read from the cache, which saved 55% on Haiku.
- **The Batch API is the next free lever.** It takes 50% off, stacks with caching, and suits evaluation runs because nobody is waiting for the answer.
- **Model choice is about validity before cost.** In this project the cheap model made the study cheap, but it also refused the attacker role and resisted every template attack. The two main questions were therefore left unanswered.
- **Deterministic code costs nothing to run.** The oracle, the egress filter, the scope check and the statistics are all deterministic code, so labelling 1,680 episodes cost nothing and can be replayed at any time. Use models at development time to help write such components, and keep model calls at run time for genuine judgement.
- **Measure everything from the API's own meters.** Every agent episode, generator call and detector call is metered and costed, and the report shows median and 95th-percentile episode time.

## 2. How an agent episode is billed

An agent episode is a loop. Each request resends the system prompt, the tool definitions and the whole conversation so far, then adds the model's next turn. For one episode with *n* requests:

```
cost ≈ Σ over requests ( uncached input × p_in
                       + cache writes   × 1.25 × p_in
                       + cache reads    × p_read
                       + output         × p_out )
```

Without caching, the resent prefix is billed at the full input price on every request, so cost grows roughly with the square of the number of turns. With caching, everything already cached is re-billed at the cache-read price, which is about a tenth of the input price for Haiku 5.5.

**Where the tokens went in the Haiku grid** (per episode, mean of 1,680):

| Meter | Tokens per episode | Price per million (Haiku 5.5) | Share of cost |
|---|---|---|---|
| Uncached input | 8 | $0.10 | 0.3% |
| Cache writes | 265 | $0.125 | 12.9% |
| Cache reads | 3,595 | $0.01 | 14.0% |
| Output, including thinking | 373 | $0.50 | 72.8% |

Four things stand out:

- **Episodes are short:** 2.9 requests on average. A long-running agent would weigh cache reads and context growth much more heavily.
- **Caching is healthy.** Cache writes are about one turn's worth per episode, not the whole conversation, which is the signature of a cache that is working.
- **Safety behaviour has a token cost.** Attacked episodes produced 378 output tokens against 271 for controls (+39%), mostly because Haiku explained the injection to the user. A defence that makes the model talk more is paid for in output tokens.
- **Defences change the token mix, not always the bill.** Spotlighting added about 260 cached input tokens per episode but reduced output slightly, so it cost the same.

## 3. Model selection

### Every role is a separate decision

`scopeeval` uses models in three roles. It deliberately uses none in a fourth, the oracle, and human raters fill the fifth.

| Role | What it needs | Choice here | Recommendation |
|---|---|---|---|
| **Agent under test** | It *is* the experimental variable | Opus 5.5 pre-registered; Haiku 5.5 run as a secondary analysis | Never pick it for cost. The model under test must be the model the question is about. Cost is controlled through episode count, caching and batching, not the model. |
| **Attacker** (writes held-out attacks) | Capability and willingness to write realistic attacks for a sandbox | Haiku 5.5, which refused every goal | A role a model may refuse needs a fallback that is *not* another model swapped in silently: human-written attacks, or a published benchmark used within its licence. Record refusals as results. |
| **LLM detector** | High-volume classification with checkable output | Haiku 5.5 (AUC 1.000 on templates) | A good fit for a small model, because outputs are scored against known labels and volume is high. Put a deterministic first stage in front of it (section 5). |
| **Oracle** (labels harm) | Reproducible, auditable, free | Deterministic code | Keep it deterministic. An LLM judge would add cost, noise and a dependency on the model being judged. |
| **Raters** (validate the oracle) | Independent human judgement | Two humans, H6 | Do not replace them with a model. The point is an independent reference. |

### Price per token is not cost per task

| | Opus 5.5 | Sonnet 5.5 | Haiku 5.5 |
|---|---|---|---|
| Input / output per million tokens | $4 / $20 | $2 / $10 | $0.10 / $0.50 |
| Cache read per million tokens | $0.20 | $0.10 | $0.01 |
| 16-episode check, measured | $0.1036 | not run | $0.0037 |
| Output tokens per episode on that check | 164 | | 269 |
| Full grid (1,680 episodes), measured | not run | not run | **$0.43** |
| Full grid, Haiku's token profile at this model's prices | $16.02 | $8.01 | $0.43 |
| Full grid, at Opus's measured cost per episode | about $11 | | |
| Same, with the Batch API (−50%) | about $5.50–8 | about $4 | about $0.22 |
| Per 100,000 episodes, Haiku's token profile | about $954 | about $477 | about $26 |

The "Haiku's token profile" rows are a what-if: real token counts differ by model. Opus wrote fewer output tokens than Haiku on the same check, which is why its measured cost per episode ($0.0065) projects to about $11 rather than $16. The only reliable figure comes from running a sample on the candidate model and reading the meters.

### A selection method that holds up

1. **Fix the quality bar first.** For an evaluation, that means the model the research question is about. For a production task, it means an evaluation set with a pass/fail check.
2. **Apply the free levers before choosing a model:** caching, input hygiene, output shape and batching (section 4). They change cost without changing the answer.
3. **Sweep effort before switching model.** On Claude 5-generation models, effort controls thinking depth and tool-call depth, and lower effort on a capable model often matches a smaller model at higher effort. Run each effort level in its own session, because changing effort mid-session restarts the cache. In `scopeeval`, effort is part of the experimental condition, so a sweep is a secondary analysis, not a saving.
4. **Then step down one tier at a time**, against the evaluation set, and **price the tail**. The cheapest model looks best on typical cases. The bill and the failures are decided by the hardest tenth.
5. **Consider two models only in the measured shapes where they pay:**
   - a cascade, where a cheap stage resolves most cases and escalates the rest;
   - an orchestrator handing bulk independent work to cheaper workers.

   For one dependent chain of work, a single model at lower effort usually wins.
6. **Do not switch models in the middle of a conversation.** Caches are per model. On models that preserve thinking, a model that did not write the earlier thinking blocks cannot read them.

### What the Haiku run teaches about selection

- **A cheaper model can make a study unanswerable rather than cheap.** Haiku resisted every template attack, so the scope comparison hit a floor. It also refused to write attacks, so the detector test had no data. Both are findings about Haiku. Neither answers the questions the study was built for.
- **Refusals in a non-target role are an operational risk.** The generator's first version would have saved Haiku's polite refusals as attacks. Any pipeline that uses a model as a tool should check stop reasons and validate content, not only the schema.
- **Cheap runs are the right way to test the pipeline.** For $0.43, the Haiku run exercised every component end to end. It also surfaced a parsing bug in the oracle before the expensive run.

## 4. Token efficiency

Apply the levers in this order. The first group is free: the answer does not change. The rest trade capability for cost and need an evaluation to justify them.

### Free levers

| Lever | Status here | Notes |
|---|---|---|
| **Prompt caching** | On: one breakpoint on the static system prompt and tools, plus automatic caching for the conversation tail | 93% of input read from cache. To stay healthy: keep anything dynamic (timestamps, IDs) out of the cached prefix, keep tool order stable, and do not change effort, thinking settings or model mid-episode. Re-check cache reads after any change to how prompts are built. |
| **Batch API** | Not implemented | 50% off every token, including cache reads and writes. Ideal for evaluation runs. A tool loop needs turn-by-turn batching: submit turn *k* of every episode as one batch, run the tools locally, then submit turn *k*+1. Results can take up to 24 hours. |
| **Input hygiene** | Small already | The tool schemas and system prompt are short. Rules for larger systems: never restate tool schemas in prose, prefer narrow tools (`lookup_customer(customer_id)`) over data dumps, and gate unbounded input with token counting. |
| **Output shape** | Not tuned | Tell the model the exact answer shape. Here, the safety warnings were the main source of extra output. In production, decide whether a one-line warning is enough. |
| **`max_tokens` as a backstop** | 16,000 per request | `max_tokens` is not a cost control. A truncated answer is a failed attempt that still costs money. |

### Trade-off levers (need an evaluation)

| Lever | When it pays |
|---|---|
| **Lower effort** | Workloads where the evaluation curve is flat. It also cuts latency. |
| **Re-run failures at higher effort** | When a cheap checker can tell a failure from a success, run everything cheaply and re-run only the failures. |
| **Task budgets** | Long loops. The model sees the budget and paces itself. |
| **A smaller model** | High-volume work with checkable outputs, such as classification or detection. Not long agentic loops where failures are costly. |

### Fewer calls

- **Adaptive top-up:** run one repeat, then add repeats only to cells whose interval is still too wide. For this design that could save up to half the grid. The rule must be pre-registered.
- **Relabel instead of re-run:** labels, filters and statistics are recomputed from stored tool logs with no API calls (`scopeeval relabel`). This is why both oracle bugs cost nothing to fix.

## 5. Use AI to build deterministic components

**Principle: use a model at build time to write and test code; at run time, use the code.** A deterministic component is free to run, instant, reproducible, versionable and auditable. A model call is none of these. Reserve run-time model calls for judgement that genuinely cannot be written down.

### What `scopeeval` already does this way

| Component | Deterministic? | What it would cost as a model call |
|---|---|---|
| Harm labelling (`oracle.py`): from final state and tool logs, never from the model's account | Yes | A judge call per episode: about 1,680 extra requests per grid, a second model's noise in every label, and no exact replay |
| Scope enforcement (`sandbox.py`): at the tool boundary | Yes | Not acceptable at all: a security boundary must not depend on a model's judgement |
| Output egress filter (`controls.py`): an allowlist of internal hosts | Yes | A classifier call per answer |
| Heuristic detector: regular expressions | Yes | AUC 0.975 on templates, for $0 |
| Statistics (`stats.py`): no dependencies | Yes | Not applicable |

### A workflow that turns model judgement into code

1. **Explore with a model.** Have a capable model label a sample, propose rules, or explain the cases it found hard.
2. **Have a human review the rules.** Keep only rules a reviewer can read and defend.
3. **Encode them as code with tests.** Write tests from real model outputs, not invented examples. This project's two oracle bugs were found by real outputs: a domain named in a warning, and a full stop after a URL. Both are now regression tests that quote the model's own wording.
4. **Version and replay.** Every label records its oracle version, and stored runs can be relabelled. A rule change is then a cheap, auditable event rather than a re-run.
5. **Measure agreement** against independent human labels (Cohen's kappa, H6). A deterministic rule can be precise and still wrong in meaning, as the "URL quoted in a refusal" case shows.
6. **Keep the model for the residue.** Use a cascade: the deterministic stage decides the clear cases, and only uncertain ones go to a model. For detection, that means running the heuristic first and calling the LLM detector only when the heuristic score falls in an uncertain band. The band should be set and validated on held-out data, not on the templates.
7. **Watch for drift.** New attack styles or model versions break rules silently. Track the share of cases escalated to the model and the agreement with human labels over time.

**Good candidates for code in an agent system:** input validation and size gates; PII detection and redaction (patterns plus checksums, with a model only for free text); routing and permission decisions; output schema validation (use structured outputs so parsing cannot fail); URL and recipient allowlists; cost and rate guards; harm and policy labels where the evidence is in logs or state.

**Poor candidates:** open-ended summarisation, intent behind unusual wording, and novel attacks. These are where a model earns its cost.

**The trade-off to keep in view:** deterministic rules are brittle at the edges. Both oracle bugs here were edge cases that only real model output exposed. The workflow above exists to find those edges cheaply: run a cheap model first, replay labels, and test with real wording.

## 6. Observability

### What the harness records

| Where | What |
|---|---|
| Each agent episode (`episodes.jsonl`) | The four token meters and request count; wall-clock seconds; outcome, with a refusal's category in `detail`; each turn's `stop_reason` in the transcript; every tool call with allowed or denied and the reason; outbox; final answer; full transcript; oracle version; harm labels and the labels after the egress filter |
| Each run (`meta.json`) | Agent, model, effort, prompt caching, grid definition, start time and any relabelling history |
| Each report (`report.md`) | Measured cost and the cost without caching, share of input read from cache, and median and 95th-percentile episode time (for runs recorded with timing; the published runs predate it) |
| The generator (`attacks/generated.usage.json`, written by each `generate` run; the published Haiku run predates it) | Token meters, cost, seconds and effort, in total and per goal with each `stop_reason` |
| The LLM detector (`detect` output) | Token meters, cost, seconds, effort and the number of refusals |

### Signals worth tracking

| Signal | Why | Healthy here |
|---|---|---|
| **Cost per completed task** | The number that matters for budgets and model choice | $0.00026 per Haiku episode |
| **Share of input read from cache** | A drop means something broke the cache: a timestamp in the prompt, a reordered tool list, an effort or model change | 93% |
| **Cache writes per episode** | Should be about one turn's worth. If it is the whole conversation, the cache is being rebuilt on every request | 265 tokens |
| **Output tokens per episode** | Rising output means more thinking or more verbose answers, and it is most of the bill | 373 (attacked) and 271 (control) |
| **`stop_reason` distribution** | `max_tokens` is a failed attempt; `refusal` needs handling; both should be rare and explained | 0 refusals, 0 truncations |
| **Latency, p50 and p95** | Capacity planning and timeouts | Not recorded in the published runs, which predate timing |
| **Denied tool calls** | A security signal: the model tried something its scope forbids | 0 |
| **Errors and retries** | 429s and 5xx responses need backoff. The SDK retries twice by default | 0 errors |
| **Harm and egress-filter hits** | The outcome being protected against | See the results |

### Tools

- **OpenTelemetry (beta).** The Claude SDKs can emit spans for each request, with token counts and latency, using the standard `gen_ai.*` attribute names. SDK tracing runs in the application's process. API tracing is configured by an organisation admin and adds server-side detail. Together they nest into one trace.
  - The default content mode is *metadata only*: no prompts or responses. Keep that default wherever prompts may contain personal or confidential data. Full content is stored under the backend's own access and retention rules.
  - Never put personal data in a conversation ID, which is exported in every mode.
  - When counting tokens from spans, sum each request once.
- **Cache diagnostics (beta).** When the cache-read share drops, the API can report where two consecutive requests diverged, without logging payloads.
- **Usage and cost reporting** at organisation level. Reconcile the harness's own cost figures with billing, from the same time window.
- **Spend limits and preflight estimates.** `scopeeval plan` prices a run before it starts, and `run` asks for confirmation. In an organisation, a workspace spend limit is the final backstop.
- **Not implemented:** logging each response's message ID with its episode, so a single episode can be matched to server-side traces and support requests.

## 7. Operational readiness checklist

Before running an agent evaluation, or any agent workload, routinely:

- **Pin everything that changes behaviour or price:** the model ID, effort, prompt and tool versions, the oracle version and the price table, and record them per run. Here, `meta.json` records the model, effort, caching and grid, and every row records its oracle version. Prompt, tool and price-table versions come only from the git commit.
- **Make runs idempotent and resumable.** Each cell has a key, and completed cells are skipped on restart.
- **Scale by partitioning, not by sharing state.** The Haiku grid ran as eight processes, one per scope and defence, each writing its own file, merged afterwards. Mind rate limits when raising concurrency.
- **Keep failures as data.** Errored episodes keep their usage, refusals are an outcome, and nothing is retried silently with another model.
- **Separate evaluation settings from production settings.** An evaluation turns refusal fallbacks off so the model under test never changes. A production system usually wants them on.
- **Keep data synthetic or redacted.** This project uses only fictional data and reserved `.example` domains. With real data, redact personal data before it reaches the model, and keep tracing to metadata only.
- **Gate spending:** a preflight estimate, a confirmation step, a spend limit, and a measured cost in every report.
- **Pre-register changes.** A dated change log stops a pipeline from quietly tuning itself to its results.
- **Run a cheap end-to-end check before an expensive run.** The Haiku runs, under $0.60 in total, found two pipeline bugs before any primary run: refusals saved as attacks, and the oracle's URL parsing.

## 8. Further optimisations for this project

None of these is implemented. They are ranked by saving and effort, and none changes a result:

1. **Batch API for grid runs:** −50%, about $5.50–8 instead of about $11–16 for an Opus 5.5 grid. Needs turn-by-turn batching.
2. **Adaptive top-up of repeats,** pre-registered: up to −50% of episodes.
3. **Cascade the detector:** heuristic first, LLM only in the uncertain band, once a held-out set exists to set the band.
4. **Log message IDs** per request, and optionally enable OpenTelemetry tracing in metadata-only mode for long runs.
5. **Settle the definition of a hijack** before the primary run, so no expensive run has to be relabelled for a definition change.
6. **An effort sweep as a secondary analysis** (low, medium, high on the primary model). It answers a useful operational question, how much safety behaviour depends on effort, without touching the primary result.
