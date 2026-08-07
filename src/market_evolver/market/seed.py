"""Small curated instrument universe; not a complete security master."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from market_evolver.company.seed import CURATED_COMPANIES
from market_evolver.knowledge.repositories import SqlKnowledgeGraph
from market_evolver.knowledge.schemas import EntityVersion, KnowledgeEntityType
from market_evolver.market.schemas import Asset, AssetType
from market_evolver.market.store import MarketDataStore

SEED_AT = datetime(2025, 1, 1, tzinfo=UTC)
PROVENANCE = ("marketevolver-v0.10-curated-asset-seed",)


def seed_assets(session: Session, store: MarketDataStore) -> int:
    graph = SqlKnowledgeGraph(session)
    for entity_id, name, entity_type in (
        ("etf.spy", "SPDR S&P 500 ETF Trust", KnowledgeEntityType.ETF),
        ("etf.vt", "Vanguard Total World Stock ETF", KnowledgeEntityType.ETF),
        ("index.ta35", "TA-35 Index", KnowledgeEntityType.INDEX),
    ):
        graph.add_entity(
            EntityVersion(
                entity_id,
                name,
                (name,),
                None,
                name,
                entity_type,
                ("US",) if entity_type is KnowledgeEntityType.ETF else ("IL",),
                (),
                SEED_AT,
                None,
                SEED_AT,
                PROVENANCE,
                1.0,
                1,
            )
        )
    assets: list[Asset] = []
    for company_id, _name, _hebrew, tase, _sector, us_symbol, _cik in CURATED_COMPANIES:
        assets.append(
            Asset(
                f"asset.xtae.{tase.casefold()}",
                tase,
                "XTAE",
                AssetType.EQUITY,
                "ILS",
                company_id,
                f"company.{company_id}",
                "asset.index.ta35",
                SEED_AT,
                None,
                SEED_AT,
                PROVENANCE,
            )
        )
        if us_symbol:
            assets.append(
                Asset(
                    f"asset.xnys.{us_symbol.casefold()}",
                    us_symbol,
                    "XNYS",
                    AssetType.EQUITY,
                    "USD",
                    company_id,
                    f"company.{company_id}",
                    "asset.arcx.spy",
                    SEED_AT,
                    None,
                    SEED_AT,
                    PROVENANCE,
                )
            )
    assets.extend(
        (
            Asset(
                "asset.arcx.spy",
                "SPY",
                "ARCX",
                AssetType.ETF,
                "USD",
                None,
                "etf.spy",
                None,
                SEED_AT,
                None,
                SEED_AT,
                PROVENANCE,
            ),
            Asset(
                "asset.arcx.vt",
                "VT",
                "ARCX",
                AssetType.ETF,
                "USD",
                None,
                "etf.vt",
                None,
                SEED_AT,
                None,
                SEED_AT,
                PROVENANCE,
            ),
            Asset(
                "asset.index.ta35",
                "TA35",
                "XTAE",
                AssetType.INDEX,
                "ILS",
                None,
                "index.ta35",
                None,
                SEED_AT,
                None,
                SEED_AT,
                PROVENANCE,
            ),
            Asset(
                "asset.fx.usdils",
                "USDILS",
                "BOI",
                AssetType.FX,
                "ILS",
                None,
                "pair.usdils",
                None,
                SEED_AT,
                None,
                SEED_AT,
                PROVENANCE,
            ),
        )
    )
    return sum(store.add_asset(item)[1] for item in assets)
