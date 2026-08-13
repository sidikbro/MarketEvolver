from market_evolver.errors import ValidationError
from market_evolver.external.schemas import ExternalBenchmarkDefinition, ExternalBenchmarkStatus


class ExternalBenchmarkRegistry:
    def __init__(self, definitions: tuple[ExternalBenchmarkDefinition, ...]) -> None:
        self._items = {item.benchmark_id: item for item in definitions}
        if len(self._items) != len(definitions):
            raise ValidationError("duplicate external benchmark ID")

    def get(self, benchmark_id: str) -> ExternalBenchmarkDefinition:
        try:
            return self._items[benchmark_id]
        except KeyError as exc:
            raise ValidationError(f"unknown external benchmark: {benchmark_id}") from exc

    def list(self) -> tuple[ExternalBenchmarkDefinition, ...]:
        return tuple(self._items[key] for key in sorted(self._items))


EXTERNAL_BENCHMARKS = ExternalBenchmarkRegistry(
    (
        ExternalBenchmarkDefinition(
            "stockbench",
            "StockBench",
            "https://github.com/ChenYXxxx/stockbench",
            "../StockBench",
            "ce8b2b3483590646ad3b650ac8221f43f76fd091",
            "Apache-2.0",
            "StockBench repository and accompanying benchmark paper",
            "historical multi-step stock decision benchmark",
            ("20 configured US equities",),
            "operator-selected historical interval",
            ("adjusted daily bars", "fundamentals", "news", "portfolio state"),
            ("structured actions", "portfolio path", "performance metrics"),
            "Historical names and news may overlap model pretraining; protocol claims are assessed separately.",
            ("Python environment", "cached data or provider credentials", "LLM provider"),
            ExternalBenchmarkStatus.INSPECTED,
            ("local-git-inspection:2026-08-13",),
        ),
        ExternalBenchmarkDefinition(
            "tradingagents",
            "TradingAgents",
            "https://github.com/tauricresearch/tradingagents",
            "../TradingAgents",
            "a33fd4c0f134485a43553a2c23a63cb14adbd88f",
            "Apache-2.0",
            "TradingAgents: Multi-Agents LLM Financial Trading Framework",
            "multi-agent single-security research and decision framework",
            ("provider-supported equities",),
            "operator-selected analysis date or backtest interval",
            ("market", "fundamentals", "news", "sentiment"),
            ("decision", "portfolio path", "reported metrics", "decision log"),
            "Named historical inputs, reflection memory, and provider data can leak later information.",
            ("Python 3.12", "data/provider credentials", "LLM provider"),
            ExternalBenchmarkStatus.INSPECTED,
            ("local-git-inspection:2026-08-13",),
        ),
        ExternalBenchmarkDefinition(
            "ktd-fin",
            "KTD-Fin",
            "https://github.com/MaYiding/OracleProto",
            None,
            None,
            "unverified",
            "From Knowing to Doing: A Memory-Controlled Benchmark for LLM Trading Agents",
            "masked leakage-controlled financial benchmark",
            ("CSI 300 methodology",),
            "paper-defined masked evaluation periods",
            ("identifier masking", "calendar masking", "market data"),
            ("market/style/selection attribution",),
            "Future adapter must verify repository, license, masks, calendars, and attribution protocol.",
            ("not inspected",),
            ExternalBenchmarkStatus.REGISTERED,
            ("paper-reference:arXiv-2605.03762",),
        ),
        ExternalBenchmarkDefinition(
            "live-trade-bench",
            "Agent Market Arena / LiveTradeBench",
            "https://github.com/ulab-uiuc/live-trade-bench",
            None,
            None,
            "unverified",
            "LiveTradeBench and Agent Market Arena live-evaluation methodologies",
            "future live multi-market evaluation",
            ("US equities", "prediction markets"),
            "live, forward-only",
            ("live market data", "live news", "portfolio state"),
            ("allocations", "live evaluation metrics"),
            "Live timing reduces some hindsight risk but does not eliminate model or information contamination.",
            ("future legal, provider, execution, and safety review",),
            ExternalBenchmarkStatus.REGISTERED,
            ("methodology-placeholder:2026-08-13",),
        ),
    )
)
