from datetime import UTC, datetime

from market_evolver.paper.schemas import RiskPolicy

NIS_2000_POLICY = RiskPolicy(
    name="NIS 2,000 conservative simulation policy",
    created_at=datetime(2025, 1, 1, tzinfo=UTC),
    max_position_weight="0.25",
    max_order_notional="400",
    max_gross_exposure="0.70",
    max_sector_exposure="0.35",
    max_currency_exposure="0.50",
    max_daily_turnover="0.40",
    max_trades_per_day=3,
    min_cash_reserve="0.30",
    max_daily_loss="0.03",
    entry_restricted_drawdown="0.06",
    max_rolling_drawdown="0.08",
    max_portfolio_drawdown="0.12",
    min_corroboration=2,
    allowed_asset_classes=("equity", "etf"),
    allowed_exchanges=("XTAE", "XNYS", "XNAS", "ARCX"),
    max_stale_seconds=86400,
    max_strategy_allocation="0.40",
    max_concurrent_positions=3,
    max_cost_order_ratio="0.03",
    max_cost_nav_ratio="0.01",
    provenance=("built-in-policy:v0.17", "simulation-only:not-financially-optimal"),
)
