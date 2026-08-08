import contextlib
import io
import unittest

from market_evolver.cli import build_parser, main


class CliTests(unittest.TestCase):
    def test_source_list_does_not_require_database_or_network(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(["source", "list"])
        self.assertEqual(result, 0)
        self.assertIn("il.boi\tenabled\tBank of Israel", output.getvalue())
        self.assertIn("il.cbs\tdisabled", output.getvalue())
        self.assertIn("il.tase.maya\tdisabled", output.getvalue())

    def test_event_observatory_commands_are_registered(self) -> None:
        parser = build_parser()
        self.assertEqual(parser.parse_args(["event", "list"]).event_command, "list")
        self.assertEqual(
            parser.parse_args(["event", "show", "event:sha256:x"]).event_id,
            "event:sha256:x",
        )
        self.assertEqual(
            parser.parse_args(["event", "replay", "--at", "2025-01-02T12:00:00+00:00"]).at,
            "2025-01-02T12:00:00+00:00",
        )

    def test_knowledge_graph_commands_are_registered(self) -> None:
        parser = build_parser()
        self.assertEqual(
            parser.parse_args(["entity", "resolve", "בנק ישראל"]).alias,
            "בנק ישראל",
        )
        self.assertEqual(
            parser.parse_args(
                [
                    "graph",
                    "trace-event",
                    "canonical-event:sha256:x",
                    "--at",
                    "2025-01-02T12:00:00+00:00",
                ]
            ).graph_command,
            "trace-event",
        )
        self.assertEqual(
            parser.parse_args(
                [
                    "graph",
                    "neighbors",
                    "sector.banks",
                    "--at",
                    "2025-01-02T12:00:00+00:00",
                ]
            ).entity_id,
            "sector.banks",
        )

    def test_news_lab_commands_are_registered(self) -> None:
        parser = build_parser()
        self.assertEqual(
            parser.parse_args(["news", "ingest", "bbc-business"]).source,
            "bbc-business",
        )
        self.assertEqual(
            parser.parse_args(["news", "replay", "--at", "2025-01-02T12:00:00+00:00"]).news_command,
            "replay",
        )
        self.assertEqual(
            parser.parse_args(["news", "show", "news:sha256:x"]).news_id,
            "news:sha256:x",
        )

    def test_news_source_list_does_not_require_database_or_network(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(["news", "source-list"])
        self.assertEqual(result, 0)
        self.assertIn('"source_id": "uk.bbc.business"', output.getvalue())

    def test_policy_commands_are_registered_and_source_list_is_offline(self) -> None:
        parser = build_parser()
        self.assertEqual(
            parser.parse_args(["policy", "ingest", "boi-interest"]).source,
            "boi-interest",
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(["policy", "source-list"])
        self.assertEqual(result, 0)
        self.assertIn('"source_id": "il.boi"', output.getvalue())

    def test_company_fundamentals_commands_are_registered(self) -> None:
        parser = build_parser()
        self.assertEqual(parser.parse_args(["company", "list"]).company_command, "list")
        self.assertEqual(parser.parse_args(["company", "show", "nice"]).company_id, "nice")
        self.assertEqual(
            parser.parse_args(
                [
                    "fundamentals",
                    "show",
                    "nice",
                    "--at",
                    "2025-01-02T12:00:00+00:00",
                ]
            ).company_id,
            "nice",
        )

    def test_research_commands_are_registered(self) -> None:
        parser = build_parser()
        context = parser.parse_args(
            [
                "research",
                "build-context",
                "nice",
                "--at",
                "2025-01-02T12:00:00+00:00",
                "--anonymize",
            ]
        )
        self.assertEqual(context.company_id, "nice")
        self.assertTrue(context.anonymize)
        self.assertEqual(
            parser.parse_args(["research", "review", "hypothesis:1"]).hypothesis_id,
            "hypothesis:1",
        )
        self.assertEqual(parser.parse_args(["filings", "list", "nice"]).company_id, "nice")
        self.assertEqual(
            parser.parse_args(
                ["exposures", "show", "nice", "--at", "2025-01-02T12:00:00+00:00"]
            ).company_id,
            "nice",
        )

    def test_market_replay_and_benchmark_commands_are_registered(self) -> None:
        parser = build_parser()
        self.assertEqual(parser.parse_args(["market", "seed-assets"]).market_command, "seed-assets")
        replay = parser.parse_args(
            ["replay", "run", "quiet", "--mode", "no_information", "--anonymized"]
        )
        self.assertEqual(replay.case, "quiet")
        self.assertTrue(replay.anonymized)
        self.assertEqual(parser.parse_args(["replay", "inspect", "run:1"]).run_id, "run:1")
        self.assertEqual(parser.parse_args(["benchmark", "report"]).benchmark_command, "report")

    def test_macro_and_trend_commands_are_registered(self) -> None:
        parser = build_parser()
        self.assertEqual(
            parser.parse_args(
                ["macro", "series", "il.cpi", "--at", "2025-01-01T00:00:00Z"]
            ).series_id,
            "il.cpi",
        )
        self.assertEqual(
            parser.parse_args(
                ["trends", "calculate", "il.cpi", "--at", "2025-01-01T00:00:00Z"]
            ).trends_command,
            "calculate",
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["macro", "source-list"]), 0)
        self.assertIn("us.fred\tdisabled", output.getvalue())

    def test_geopolitical_commands_and_source_list_are_registered(self) -> None:
        parser = build_parser()
        replay = parser.parse_args(["geopolitical", "replay", "--at", "2025-01-01T00:00:00Z"])
        self.assertEqual(replay.geopolitical_command, "replay")
        self.assertEqual(
            parser.parse_args(["geopolitical", "show", "geo:1"]).event_id,
            "geo:1",
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["geopolitical", "source-list"]), 0)
        self.assertIn("global.icao\tdisabled", output.getvalue())
        self.assertIn("uk.bbc.business\tenabled", output.getvalue())


if __name__ == "__main__":
    unittest.main()
