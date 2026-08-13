# External benchmark environments

Version 0.29 brings up StockBench and TradingAgents in separate, disposable
Conda prefixes. Neither package is installed into MarketEvolver's environment,
and neither sibling checkout is edited. Exact repository SHAs, dependency-file
hashes, resolved-environment hashes, Python versions, package counts, selected
installed versions, and smoke outcomes are recorded in
`config/external/v029-environments.json`.
The complete installed package snapshots are
`config/external/stockbench-v029.freeze.txt` and
`config/external/tradingagents-v029.freeze.txt`; their file hashes are the
manifest's `pip_freeze_sha256` values.

## Reproduction and cleanup

Use Python 3.12 and create one prefix per project. StockBench is installed from
its unchanged `requirements.txt`. TradingAgents' `requirements.txt` contains
only `.`, whose meaning depends on the caller's working directory; therefore the
audited installation explicitly targets the sibling project and its declared
`dev` extra. Never run that requirements file from MarketEvolver.

The tested prefixes were `/tmp/marketevolver-stockbench-v029` and
`/tmp/marketevolver-tradingagents-v029`. They contain no credentials and may be
removed after inspection. Recreate them rather than reusing an environment
whose freeze hash differs from the manifest.

StockBench installed 58 packages. Imports passed, but the native CLI failed
with `TypeError: Secondary flag is not valid for non-boolean flag` under its
resolved Typer 0.12.5 and Click 8.4.2. This is `BLOCKED_DEPENDENCY`; no pin or
source compatibility patch was applied.

TradingAgents installed 113 packages. Imports and CLI help passed; 14 selected
native date-boundary and signal-processing tests passed.

## Network and credentials

`market-evolver external network-manifest` emits explicit domains, credential
variable names, and download classes. Broad network access is forbidden.
Credential presence may be recorded; values must never enter logs or manifests.
Caches and external outputs remain outside the repository.

DeepSeek validation requires `DEEPSEEK_API_KEY`. StockBench can also require
`FINNHUB_API_KEY` and `POLYGON_API_KEY`. TradingAgents may require
`ALPHA_VANTAGE_API_KEY` and `FRED_API_KEY`; configured paths can also reach
Yahoo Finance, Polymarket, Reddit, and StockTwits. Grant only domains needed by
the approved case.
