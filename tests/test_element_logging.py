import inspect
import logging
import pickle
import unittest

import cardtable as c
from cardtable.core.closure import Closure
from cardtable.widgets.elements.button import ButtonControl


class ElementLoggingTest(unittest.TestCase):
    def tearDown(self):
        Closure().close_all()

    def test_element_constructors_accept_and_validate_log_level(self):
        factories = [
            lambda **kw: c.Label("hello", **kw),
            lambda **kw: c.Entry(**kw),
            lambda **kw: c.Table(["column"], 2, **kw),
            lambda **kw: c.SignalPlot(**kw),
            lambda **kw: c.LED("red", **kw),
            lambda **kw: c.Button("run", **kw),
            lambda **kw: c.TrueBtn("yes", **kw),
        ]
        for factory in factories:
            with self.subTest(factory=factory):
                self.assertEqual(factory()._log_level, logging.DEBUG)
                self.assertEqual(factory(log_level="INFO")._log_level, logging.INFO)
                with self.assertRaises(ValueError):
                    factory(log_level="invalid")
        self.assertEqual(ButtonControl(c.Button("run")).log_level, logging.INFO)
        self.assertEqual(
            ButtonControl(c.Button("run", log_level="DEBUG")).log_level, logging.DEBUG
        )
        self.assertIn("log_level", inspect.signature(c.Label).parameters)
        self.assertIn("log_level", inspect.signature(c.Entry).parameters)

    def test_public_methods_log_configured_level_without_values_or_nested_calls(self):
        text = c.Text(log_level="INFO")
        with self.assertLogs("cardtable.widgets.elements.base", level="INFO") as logs:
            text.set("secret")
            text.append(" text")
            text.get()
            text.reset()
        self.assertEqual(
            [record.cardtable_caller for record in logs.records],
            ["Text.set", "Text.append", "Text.get", "Text.reset"],
        )
        self.assertTrue(all(record.levelno == logging.INFO for record in logs.records))
        self.assertTrue(
            all("secret" not in record.getMessage() for record in logs.records)
        )
        self.assertTrue(
            all(text.name in record.getMessage() for record in logs.records)
        )

    def test_default_debug_and_custom_subclass_and_serialization(self):
        class Custom(c.Label):
            def clear(self):
                self.set("")

        element = Custom("hello")
        with self.assertLogs("cardtable.widgets.elements.base", level="DEBUG") as logs:
            element.clear()
            element.get()
        self.assertEqual(
            [record.cardtable_caller for record in logs.records],
            ["Custom.clear", "Custom.get"],
        )
        self.assertTrue(all(record.levelno == logging.DEBUG for record in logs.records))
        entry = pickle.loads(pickle.dumps(c.Entry(log_level="WARNING")))
        self.assertEqual(entry._log_level, logging.WARNING)

    def test_table_and_signal_plot_specific_operations(self):
        table = c.Table(["a"], 2)
        plot = c.SignalPlot()
        with self.assertLogs("cardtable.widgets.elements.base", level="DEBUG") as logs:
            table.append([1])
            table.extend([[2]])
            plot.append(1)
            plot.expand([2])
        self.assertEqual(
            [record.cardtable_caller for record in logs.records],
            ["Table.append", "Table.extend", "SignalPlot.append", "SignalPlot.expand"],
        )

    def test_method_overrides_and_global_level(self):
        table = c.Table(["name", "value"], 10, log_levels={"set": "INFO"})
        with self.assertLogs("cardtable.widgets.elements.base", level="INFO") as logs:
            table.set([["temperature", 25]])
            table.get()
            table.reset()
        self.assertEqual([r.cardtable_caller for r in logs.records], ["Table.set"])
        self.assertEqual(logs.records[0].levelno, logging.INFO)

        with self.assertLogs("cardtable.widgets.elements.base", level="DEBUG") as logs:
            table.set([["temperature", 25]])
            table.get()
            table.reset()
        self.assertEqual(
            [(r.cardtable_caller, r.levelno) for r in logs.records],
            [("Table.set", logging.INFO), ("Table.get", logging.DEBUG),
             ("Table.reset", logging.DEBUG)],
        )

    def test_method_overrides_are_validated_and_copied(self):
        levels = {"set": "INFO", "get": logging.WARNING}
        element = c.Entry(log_levels=levels)
        levels["set"] = "ERROR"
        self.assertEqual(
            element._log_levels, {"set": logging.INFO, "get": logging.WARNING}
        )
        restored = pickle.loads(pickle.dumps(element))
        self.assertEqual(restored._log_levels, element._log_levels)
        self.assertIn("log_levels", inspect.signature(c.Entry).parameters)

    def test_constructor_definitions_expose_logging_arguments(self):
        classes = (
            c.Element, c.InputElement, c.Entry, c.CheckBox, c.Switch, c.Slider,
            c.Number, c.RangeSlider, c.Radio, c.ComboBox, c.FileDrop, c.FileDialog,
            c.LED, c.Label, c.BoxedLabel, c.Image, c.Text, c.Table, c.Gauge,
            c.ProgressBar, c.SignalPlot, c.Button, c.TrueBtn, c.FalseBtn,
            c.CancelBtn, c.Separator,
        )
        for cls in classes:
            with self.subTest(element=cls.__name__):
                parameters = inspect.signature(cls.__init__).parameters
                self.assertIn("log_level", parameters)
                self.assertIn("log_levels", parameters)
        for invalid in ({"append": "INFO"}, {"missing": "INFO"}, {"set": "bad"}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                c.Entry(log_levels=invalid)
        with self.assertRaises(TypeError):
            c.Entry(log_levels=[("set", "INFO")])
        with self.assertRaises(TypeError):
            c.Entry(log_levels={1: "INFO"})

    def test_method_override_does_not_change_button_trigger_level(self):
        button = c.Button("run", log_levels={"disable": "WARNING"})
        self.assertEqual(button._log_levels["disable"], logging.WARNING)
        self.assertEqual(ButtonControl(button).log_level, logging.INFO)
