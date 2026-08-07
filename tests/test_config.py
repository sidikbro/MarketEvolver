import tempfile
import unittest
from pathlib import Path

from market_evolver.config import load_config
from market_evolver.errors import GovernanceViolation


class ConfigTests(unittest.TestCase):
    def test_default_config_is_non_executing(self) -> None:
        config = load_config(Path(__file__).parents[1] / "config" / "default.toml")
        self.assertFalse(config.governance.allow_execution)
        self.assertFalse(config.runtime_permissions.broker_access)

    def test_execution_cannot_be_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.toml"
            path.write_text("[governance]\nallow_execution = true\n", encoding="utf-8")
            with self.assertRaises(GovernanceViolation):
                load_config(path)

    def test_model_output_and_permissions_are_distinct_types(self) -> None:
        config = load_config(Path(__file__).parents[1] / "config" / "default.toml")
        self.assertFalse(hasattr(config.runtime_permissions, "recommendation"))


if __name__ == "__main__":
    unittest.main()
