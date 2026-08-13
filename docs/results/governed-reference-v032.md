# Governed reference v0.32

Version 0.32 validates forward evidence acquisition and governed research. It is
not a trading-performance release and does not compare returns with external
baselines.

## Planned live evidence

The initial universe is `pair.usdils`. Only the reviewed BOI current-policy API
and BBC Business RSS contracts are enabled. Telegram, MAYA, geopolitical feeds,
and unreviewed sources remain disabled. Every newly retrieved document is
classified `observed_live_at_time`; no observation is backdated or described as
historical evidence.

The sufficiency gate requires at least two independent source IDs, an
authoritative official source, reviewed-news corroboration, at least two records,
and no future observation. Failure produces `BLOCKED_EVIDENCE` before any model
call.

## Governed research

If the context passes, the same eligible context is used for the General Market
Researcher, fixed relevant specialist, and specialist plus skeptical reviewer.
DeepSeek `deepseek-v4-flash` is limited to four campaign calls (including one
possible exhaustion retry) and 8,192 output tokens per subsequent call. Usage,
reasoning tokens where exposed, visible output tokens, request IDs,
response hashes, latency, and cost are retained independently of semantic
parsing. Empty output at the reasoning limit is
`MODEL_OUTPUT_EXHAUSTED`, never a trading action.

## v0.31 operational lessons

StockBench was observed to ignore the requested single-agent mode, make three
LLM calls, scan 1,797 news cache files, receive an empty decision response after
output-token exhaustion, and fall back to HOLD. TradingAgents produced ten
DeepSeek responses before failure, exposed no native token/cost accounting, and
produced no final decision envelope. These are observations from the bounded
v0.31 runs, not broader claims about either project.

## Live result

The live acquisition completed on 2026-08-13. The research cutoff was
`2026-08-13T12:22:28.641688Z`.

| Source | Classification | Raw bytes | Normalized bytes |
|---|---|---:|---:|
| `il.boi` current-policy API | `observed_live_at_time` | 112 | 83 |
| `uk.bbc.business` RSS | `observed_live_at_time` | 38,070 | 16,797 |

Both raw and normalized artifacts are content-addressed locally. The committed
run manifest retains hashes, sizes, retrieval/first-observed/publication/server
timestamps, source IDs, response metadata, and vintage IDs, but not unrestricted
raw third-party content. The context contained two evidence records from two
independent source IDs, including one authoritative official source and one
reviewed-news source. The sufficiency gate passed with zero stale or future
records.

The first General Market Researcher attempt exhausted a 4,096-token completion:
3,771 reasoning tokens and 325 visible tokens, `finish_reason=length`. Its usage,
request ID, response hash, latency, and cost were retained and its status is
`MODEL_OUTPUT_EXHAUSTED`. It produced no accepted claims. A single bounded retry
used an 8,192-token allowance and completed, after which the specialist and
reviewer ran on the same eligible evidence context.

| Mode | Input | Output | Reasoning | Visible | Latency ms | Cost USD | Claims |
|---|---:|---:|---:|---:|---:|---:|---:|
| Generalist exhausted attempt | 708 | 4,096 | 3,771 | 325 | 36,942 | 0.001246 | 0 accepted |
| General Market Researcher | 714 | 7,168 | 6,423 | 745 | 62,892 | 0.002107 | 5 |
| Fixed relevant specialist | 715 | 1,864 | 1,103 | 761 | 17,629 | 0.000622 | 4 |
| Specialist skeptical reviewer | 973 | 3,315 | 2,516 | 799 | 30,694 | 0.001064 | 4 |
| **Total** | **3,110** | **16,443** | **13,813** | **2,630** | **148,157** | **0.005039** | **13** |

The ID/temporal grounding audit classified five claims `SUPPORTED`, six
`PARTIALLY_SUPPORTED`, two `UNSUPPORTED`, and zero `CONTRADICTED`. The two
unsupported claims expanded “BOI” as “Bank of Ireland”; the accepted official
source was the Bank of Israel (`il.boi`). These claims were deterministically
rejected after generation. The model reviewer accepted four claims, rejected
none, and did not catch either entity error. This is a concrete reviewer weakness
and must remain visible rather than being repaired in prose.

Temporal leakage was zero: every `first_observed_at` preceded the cutoff, and no
future revision or outcome data entered the context. No paper trade or runtime
action was created.

A specialist hypothesis with explicit uncertainty and both accepted vintage IDs
was sealed as
`sealed-research-commitment:sha256:36da4d76d82175263822f4220b47884c82a15e58b159287c90e14d0a6d5c14e3`.
It commits a bounded 2026-09-01 policy hypothesis for future evaluation and does
not assert a trading recommendation.

Across the initial acquisition and bounded retry, the archive downloaded 76,364
raw bytes and produced 33,760 normalized bytes, four live vintages, five unique
content-addressed artifacts, and zero revisions. Source/day totals were two BOI
snapshots (224 raw bytes) and two BBC snapshots (76,140 raw bytes).

The immutable sanitized run record is
`config/v032-governed-reference-run.json`.
