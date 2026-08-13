# External benchmarks

Version 0.27 introduces a read-only boundary for external financial-agent
benchmarks. External source trees remain sibling repositories; MarketEvolver
stores definitions, inspection manifests, comparison contracts, normalized
results, and provenance only. It does not vendor source, datasets, credentials,
or external logs containing protected data.

The inspected pins are:

| Benchmark | Git SHA | Remote | License | State |
|---|---|---|---|---|
| StockBench | `ce8b2b3483590646ad3b650ac8221f43f76fd091` | `ChenYXxxx/stockbench` | Apache-2.0 | inspected, not runnable |
| TradingAgents | `a33fd4c0f134485a43553a2c23a63cb14adbd88f` | `tauricresearch/tradingagents` | Apache-2.0 | inspected, not runnable |
| KTD-Fin | unpinned | methodology placeholder | unverified | registered |
| Agent Market Arena / LiveTradeBench | unpinned | live-evaluation placeholder | unverified | registered |

“Inspected” means the local sibling was clean and its SHA, remote, dependency
files, license, and relevant configuration were hashed. It does not mean that
provider credentials, datasets, environment compatibility, or a fair run are
available. Execution requires an explicit operator approval and a clean checkout
at the registered SHA. No full benchmark was executed in v0.27.

Every comparison manifest must state assets, period, capital, costs, execution
timing, information set, provider/model/settings, call count, benchmark,
currency, and fractional-share policy. A difference in market/economic protocol
is `NON_EQUIVALENT`; model or call-count differences with the same economic
protocol are `PARTIALLY_COMPARABLE`; only identical declared fields are
`EXACTLY_COMPARABLE`. Reports never infer a winner for incompatible runs.

Common financial metrics are normalized only through explicit aliases. Native
MarketEvolver safety, grounding, leakage, provenance, and review metrics remain
separate. External claims about contamination controls are recorded as protocol
claims, not accepted as proof. Named historical assets, news, current provider
data, benchmark composition, and model pretraining all remain leakage risks.

CLI inspection is offline:

```bash
market-evolver external list
market-evolver external inspect stockbench
market-evolver external verify-sha tradingagents
market-evolver external compare-manifest left.json right.json
market-evolver external report left.json right.json
```

KTD-Fin requires future verification of its repository and license plus
identifier/calendar masking and return-attribution decomposition. Live arena
work requires a separate legal, provider, execution, and safety review; it is
not a route to live trading in MarketEvolver.

Version 0.28 adds immutable provider/environment profiles, bounded DeepSeek
validation, actual token/latency/cost accounting, repeated-run aggregation, and
explicit execution blockers. See [the v0.28 result](results/external-benchmark-v028.md):
credentials and verified datasets were unavailable, so no performance result
was generated.
