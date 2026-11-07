import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cardtable as c
from cardtable.core import config_manager


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.path_patch = patch.object(config_manager, "_config_path", None)
        self.config_patch = patch.object(config_manager, "_config", {})
        self.path_patch.start()
        self.config_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.addCleanup(self.config_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.yaml"

    def test_dealer_loads_config_before_setup_and_reload_returns_snapshot(self):
        self.path.write_text("app:\n  interval: 5\n", encoding="utf-8")

        class App(c.Dealer):
            def setup(self):
                self.initial = c.get_config()

        app = App(config_path=str(self.path))
        self.addCleanup(app.close)
        self.assertEqual(app.initial, {"app": {"interval": 5}})
        app.initial["app"]["interval"] = 99
        self.assertEqual(c.get_config()["app"]["interval"], 5)
        self.path.write_text("app:\n  interval: 10\n", encoding="utf-8")
        self.assertEqual(c.get_config()["app"]["interval"], 5)
        self.assertEqual(c.reload_config(), {"app": {"interval": 10}})
        self.assertEqual(c.get_config()["app"]["interval"], 10)

    def test_missing_invalid_or_unconfigured_file(self):
        self.assertEqual(c.get_config(), {})
        with self.assertRaises(RuntimeError):
            c.reload_config()
        with self.assertRaises(FileNotFoundError):
            config_manager._set_config_path(self.path)
        self.path.write_text("value: 1\n", encoding="utf-8")
        config_manager._set_config_path(self.path)
        self.path.write_text("- invalid\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            c.reload_config()
        self.assertEqual(c.get_config(), {"value": 1})
