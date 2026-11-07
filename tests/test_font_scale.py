"""Common font scaling, UI transport, and Gauge's dial exception."""

import inspect
import math
import pickle
import subprocess
import sys
import textwrap
import unittest

import cardtable as c


class FontScaleTest(unittest.TestCase):
    def test_common_argument_validation_signature_and_transport(self):
        factories = [
            lambda **kw: c.Element(**kw),
            lambda **kw: c.Label("label", **kw),
            lambda **kw: c.BoxedLabel("badge", **kw),
            lambda **kw: c.Entry(**kw),
            lambda **kw: c.CheckBox(**kw),
            lambda **kw: c.Switch(**kw),
            lambda **kw: c.Radio(["a", "b"], **kw),
            lambda **kw: c.ComboBox(["a", "b"], **kw),
            lambda **kw: c.Slider(0, 10, 1, **kw),
            lambda **kw: c.RangeSlider(0, 10, 1, **kw),
            lambda **kw: c.Number(0, 10, 1, **kw),
            lambda **kw: c.FileDialog(**kw),
            lambda **kw: c.FileDrop(**kw),
            lambda **kw: c.Text(**kw),
            lambda **kw: c.Image(**kw),
            lambda **kw: c.Table(["column"], 2, **kw),
            lambda **kw: c.SignalPlot(**kw),
            lambda **kw: c.ProgressBar(**kw),
            lambda **kw: c.Gauge(**kw),
            lambda **kw: c.LED("red", **kw),
            lambda **kw: c.Button("run", **kw),
            lambda **kw: c.TrueBtn("yes", **kw),
            lambda **kw: c.Separator("section", **kw),
        ]
        for factory in factories:
            element = factory(font_scale=1.5)
            with self.subTest(element=type(element).__name__):
                self.assertEqual(factory().font_scale, 1.0)
                self.assertEqual(element.font_scale, 1.5)
                self.assertEqual(pickle.loads(pickle.dumps(element)).font_scale, 1.5)
                parameter = inspect.signature(type(element).__init__).parameters[
                    "font_scale"
                ]
                self.assertEqual(parameter.default, 1.0)
                self.assertEqual(parameter.kind, inspect.Parameter.KEYWORD_ONLY)
                for invalid in (True, "1.5", None):
                    with self.assertRaises(TypeError):
                        factory(font_scale=invalid)
                for invalid in (0, -1, math.nan, math.inf, -math.inf):
                    with self.assertRaises(ValueError):
                        factory(font_scale=invalid)

    def test_real_fonts_and_gauge_exception(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent("""
                import pickle
                import tkinter.font as tkfont
                import customtkinter as ctk
                import cardtable as c
                from cardtable.widgets.elements._fonts import ctk_font, tk_font

                root = ctk.CTk()
                root.withdraw()
                original = tkfont.nametofont("TkDefaultFont").actual()
                standard = ctk_font(1)
                enlarged = ctk_font(1.5)
                assert abs(enlarged.cget("size") - standard.cget("size") * 1.5) <= 1
                native = tk_font(1.5)
                assert native.cget("size") == round(original["size"] * 1.5)
                assert tkfont.nametofont("TkDefaultFont").actual() == original

                entry = c.Entry(label="Input", font_scale=1.5)
                entry.build_ui(root, lambda _: None)
                for widget in (entry._ui._label, entry._ui._entry):
                    assert widget.cget("font").cget("size") == enlarged.cget("size")
                combo = c.ComboBox(["a", "b"], font_scale=1.5)
                combo.build_ui(root, lambda _: None)
                widget = combo._ui._controls[0]
                assert widget.cget("font").cget("size") == enlarged.cget("size")
                dropdown_size = widget.cget("dropdown_font").cget("size")
                assert dropdown_size == enlarged.cget("size")

                text = c.Text(label="Text", font_scale=1.5)
                text.build_ui(root, lambda _: None)
                assert text._ui._font.cget("size") == native.cget("size")
                table = c.Table(["Column"], 2, font_scale=1.5)
                table.build_ui(root, lambda _: None)
                assert table._ui._font.cget("size") == native.cget("size")
                bar = c.ProgressBar(font_scale=1.5)
                bar.build_ui(root, lambda _: None)
                assert bar._ui._font.cget("size") == enlarged.cget("size")
                badge = c.BoxedLabel("Badge", font=("Arial", 16), font_scale=1.5)
                badge.build_ui(root, lambda _: None)
                assert badge._ui.cget("font") == ("Arial", 24, "bold")
                badge.set(font=("Arial", 20))
                badge.update_ui(badge.display_value(badge.get()))
                assert badge._ui.cget("font") == ("Arial", 30, "bold")
                badge.reset()
                badge.update_ui(badge.display_value(badge.get()))
                assert badge._ui.cget("font") == ("Arial", 24, "bold")

                gauge = c.Gauge(unit="%", font_scale=1)
                gauge.build_ui(root, lambda _: None)
                control = gauge._ui
                control._layout(320)
                dial_items = (control._minimum, control._maximum,
                              control._unit, control._caption)
                dial_before = [control._surface.itemcget(item, "font")
                               for item in dial_items]
                geometry_before = control._geometry
                gauge.configure(font_scale=1.5)
                gauge.update_ui(gauge.display_value(gauge.get()))
                control._layout(320)
                label_size = control._label.cget("font").cget("size")
                assert label_size == enlarged.cget("size")
                assert control._geometry == geometry_before
                assert dial_before == [control._surface.itemcget(item, "font")
                                       for item in dial_items]
                assert gauge.font_scale == 1.5
                gauge.reset()
                assert gauge.font_scale == 1
                for element in (entry, combo, text, table, bar, badge, gauge):
                    restored = pickle.loads(pickle.dumps(element))
                    assert restored.font_scale == element.font_scale
                    assert not hasattr(restored, "_ui")
                root.destroy()
            """),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
