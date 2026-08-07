import contextlib
import io
import unittest

from market_evolver.cli import main


class CliTests(unittest.TestCase):
    def test_source_list_does_not_require_database_or_network(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(["source", "list"])
        self.assertEqual(result, 0)
        self.assertIn("il.boi\tenabled\tBank of Israel", output.getvalue())
        self.assertIn("il.cbs\tdisabled", output.getvalue())
        self.assertIn("il.tase.maya\tdisabled", output.getvalue())


if __name__ == "__main__":
    unittest.main()
