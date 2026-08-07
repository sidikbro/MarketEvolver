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


if __name__ == "__main__":
    unittest.main()
