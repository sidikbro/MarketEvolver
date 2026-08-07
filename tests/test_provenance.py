import unittest
from datetime import UTC, datetime, timedelta, timezone

from market_evolver.provenance import canonical_json
from market_evolver.schemas import Source, SourceKind

NOW = datetime(2025, 1, 2, 12, tzinfo=UTC)


class ProvenanceTests(unittest.TestCase):
    def test_content_ids_are_deterministic(self) -> None:
        kwargs = {
            "uri": "https://example.test/item",
            "kind": SourceKind.NEWS,
            "publisher": "Example",
            "published_at": NOW,
            "observed_at": NOW,
            "ingested_at": NOW,
            "content_digest": "sha256:abc",
        }
        self.assertEqual(Source(**kwargs).provenance_id, Source(**kwargs).provenance_id)

    def test_equivalent_timezones_have_the_same_identity(self) -> None:
        offset_time = NOW.astimezone(timezone(timedelta(hours=2)))
        utc_source = Source("x", SourceKind.NEWS, "p", NOW, NOW, NOW, content_digest="sha256:x")
        offset_source = Source(
            "x",
            SourceKind.NEWS,
            "p",
            offset_time,
            offset_time,
            offset_time,
            content_digest="sha256:x",
        )
        self.assertEqual(utc_source.provenance_id, offset_source.provenance_id)

    def test_canonical_json_sorts_mapping_keys(self) -> None:
        self.assertEqual(canonical_json({"b": 1, "a": 2}), canonical_json({"a": 2, "b": 1}))


if __name__ == "__main__":
    unittest.main()
