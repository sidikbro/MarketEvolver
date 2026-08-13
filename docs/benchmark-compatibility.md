# Benchmark compatibility

Version 0.30 separates native benchmark execution from controlled compatibility
execution. Native results retain each project's original protocol and are
always labeled `NATIVE_ONLY`. Controlled results normalize only asset, period,
capital, long-only constraints, repeat count, and model profile where their
public interfaces support it. Remaining mismatches are never erased.

## StockBench environment resolution

Pinned StockBench declares `typer>=0.9.0,<0.13.0` and no direct Click version.
The v0.29 environment resolved Typer 0.12.5 and Click 8.4.2. Its native help
command failed with `TypeError: Secondary flag is not valid for non-boolean
flag`, while constructing the `Optional[bool]` option.

Installing Click 8.1.8 in the isolated StockBench environment—without changing
requirements or source—made `python -m stockbench.apps.run_backtest --help`
pass. `pip check` reported no broken requirements. This is
`ENVIRONMENT_COMPATIBILITY`, not `PATCHED_BASELINE`. The updated freeze hash is
recorded in `config/external/v030-pilot-manifest.json`. The external checkout
remained clean at its pinned SHA.

StockBench's native profile names an old DeepSeek model. A separate operator
configuration can use the existing OpenAI-compatible client with the current
endpoint/model without source modification, but exact compatibility cannot be
asserted until the provider returns its model identity. Native and controlled
profiles must remain separate artifacts.

## Model classification

MarketEvolver and TradingAgents configure `deepseek-v4-flash`. StockBench can
receive that profile through configuration, but its native profile differs.
Because no DeepSeek credential was present, server-returned identity is unknown
and all three are currently `BLOCKED`, not `EXACT_MODEL`. A configured alias is
never treated as proof of server identity.

## Fairness

The native MarketEvolver/StockBench and MarketEvolver/TradingAgents layers are
`NATIVE_ONLY`. The controlled StockBench layer remains `NON_EQUIVALENT` because
its cached evidence has no causal-vintage proof. The controlled TradingAgents
layer is also `NON_EQUIVALENT`: current/ambiguous vendor inputs can leak later
fundamentals, edited news, and present social context into a historical date.

These classifications can change only from new manifests and successful gates,
not from favorable pilot outcomes.
