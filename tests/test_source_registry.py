import unittest

from market_evolver.errors import ValidationError
from market_evolver.sources.registry import (
    DEFAULT_REGISTRY,
    AuthorityTier,
    IngestionMethod,
    RegistrySourceType,
    SourceDefinition,
    SourceRegistry,
)


class SourceRegistryTests(unittest.TestCase):
    def test_initial_official_sources_are_registered(self) -> None:
        self.assertEqual(
            {item.source_id for item in DEFAULT_REGISTRY.list()},
            {
                "il.boi",
                "il.cbs",
                "il.tase.maya",
                "uk.bbc.business",
                "il.mof",
                "il.isa",
                "il.knesset",
                "il.competition",
                "il.tax",
                "us.sec.edgar",
                "us.fred",
                "eu.ecb.data",
                "global.worldbank",
                "global.oecd.sdmx",
                "us.eia",
                "il.pmo.statements",
                "il.idf.statements",
                "us.state.statements",
                "global.un.press",
                "global.icao",
                "global.imo",
                "global.iea",
            },
        )
        self.assertTrue(DEFAULT_REGISTRY.get("il.boi").enabled)
        self.assertTrue(DEFAULT_REGISTRY.get("il.cbs").enabled)
        self.assertFalse(DEFAULT_REGISTRY.get("il.tase.maya").enabled)

    def test_registry_rejects_duplicate_stable_ids(self) -> None:
        source = SourceDefinition(
            source_id="il.test",
            name="Test Authority",
            source_type=RegistrySourceType.GOVERNMENT,
            geography="IL",
            authority_tier=AuthorityTier.OFFICIAL_PRIMARY,
            base_uri="https://example.test",
            expected_content_types=("application/json",),
            timezone="Asia/Jerusalem",
            ingestion_method=IngestionMethod.JSON_API,
            enabled=False,
            revision_notes="Test data can be revised.",
        )
        with self.assertRaises(ValidationError):
            SourceRegistry((source, source))

    def test_registry_rejects_insecure_or_unknown_timezone_sources(self) -> None:
        with self.assertRaises(ValidationError):
            SourceDefinition(
                source_id="il.test",
                name="Test",
                source_type=RegistrySourceType.GOVERNMENT,
                geography="IL",
                authority_tier=AuthorityTier.OFFICIAL_PRIMARY,
                base_uri="http://example.test",
                expected_content_types=("application/json",),
                timezone="Not/AZone",
                ingestion_method=IngestionMethod.JSON_API,
                enabled=False,
                revision_notes="May revise.",
            )

    def test_registry_rejects_malformed_stable_id(self) -> None:
        with self.assertRaises(ValidationError):
            SourceDefinition(
                source_id="il..test",
                name="Test",
                source_type=RegistrySourceType.GOVERNMENT,
                geography="IL",
                authority_tier=AuthorityTier.OFFICIAL_PRIMARY,
                base_uri="https://example.test",
                expected_content_types=("application/json",),
                timezone="Asia/Jerusalem",
                ingestion_method=IngestionMethod.JSON_API,
                enabled=False,
                revision_notes="May revise.",
            )


if __name__ == "__main__":
    unittest.main()
