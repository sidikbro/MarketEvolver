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


if __name__ == "__main__":
    unittest.main()
