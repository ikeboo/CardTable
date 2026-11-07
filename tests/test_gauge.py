"""Gauge value lifecycle, process transport and retained rendering."""

import math
import pickle
import subprocess
import sys
import textwrap
import unittest
from unittest.mock import Mock

from test_widgets import FakeRuntime

from cardtable import Card, Element, Gauge
from cardtable.core.closure import Closure


class GaugeTest(unittest.TestCase):
    def tearDown(self):
        Closure().close_all()

    def test_values_lifecycle_and_atomic_configuration(self):
        gauge = Gauge(
            (0, 50, 70, 80, 100),
            unit="%",
            colors=["gray", "green", "yellow", "red"],
            label="Value",
            default_value=24.6,
        )
        self.assertIsInstance(gauge, Element)
        gauge.set(56)
        self.assertIs(type(gauge.get()), int)
        gauge.set(56.0)
        self.assertIs(type(gauge.get()), float)
        gauge.disable()
        gauge.set(-20, configure={"label": "Changed", "unit": "V"})
        self.assertEqual(gauge.get(), -20)
        self.assertFalse(gauge.is_enabled())
        gauge.clear()
        self.assertIsNone(gauge.get())
        gauge.configure(font_scale=1.5, colors=["red"] * 4)
        gauge.reset()
        self.assertEqual(gauge.get(), 24.6)
        self.assertEqual(gauge.label, "Value")
        self.assertEqual(gauge.unit, "%")
        self.assertEqual(gauge.colors, ("gray", "green", "yellow", "red"))
        self.assertTrue(gauge.is_enabled())
        for value in (True, "56", math.nan, math.inf):
            with self.assertRaises((TypeError, ValueError)):
                gauge.set(value, configure={"label": "Invalid"})
            self.assertEqual(gauge.label, "Value")
            self.assertEqual(gauge.get(), 24.6)
        for config in (
            {"colors": ["red"]},
            {"width": 0},
            {"height": True},
            {"font_scale": math.nan},
            {"label": 2},
            {"unit": None},
            {"enabled": 1},
            {"bg_color": "bad color"},
            {"typo": 1},
        ):
            before = gauge.display_value(gauge.get())
            with self.assertRaises((TypeError, ValueError)):
                gauge.set(99, configure=config)
            self.assertEqual(gauge.display_value(gauge.get()), before)

    def test_scale_validation_and_defaults(self):
        for bounds in ((), (0,), (0, 0), (1, 0), (0, math.inf), (False, 2)):
            with self.assertRaises((TypeError, ValueError)):
                Gauge(bounds)
        gauge = Gauge((-50, 0, 100))
        self.assertEqual(gauge.get(), -50)
        gauge.enable()
        self.assertTrue(gauge.is_enabled())

    def test_card_transport_pickle_and_duplicate_suppression(self):
        runtime = FakeRuntime()
        with Card(0, 0, 4, 3, "Gauge", runtime=runtime) as card:
            gauge = Gauge()
        card.start()
        gauge.set(56)
        self.assertEqual(card.values(), (56,))
        data = pickle.loads(pickle.dumps(runtime.updates[-1][1][gauge.name]))
        self.assertEqual(data["value"], 56)
        count = len(runtime.updates)
        gauge.set(56)
        gauge.configure(label=None)
        self.assertEqual(len(runtime.updates), count)
        gauge._ui = Mock()
        copied = pickle.loads(pickle.dumps(gauge))
        self.assertFalse(hasattr(copied, "_ui"))
        self.assertEqual(copied.get(), 56)
        gauge.clear()
        self.assertIsNone(runtime.updates[-1][1][gauge.name]["value"])

    def test_native_rendering_and_update_cost(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent("""
                import tkinter as tk
                import customtkinter as ctk
                from unittest.mock import patch
                from cardtable import Gauge, Label
                try:
                    root = ctk.CTk()
                except tk.TclError:
                    print("NO_DISPLAY")
                    raise SystemExit(0)
                root.geometry("600x380")
                g = Gauge((0, 50, 70, 80, 100), unit="%",
                          colors=["gray", "green", "yellow", "red"], label="Value")
                g.set(24.6)
                g.build_ui(root, None)
                following = Label("Following element")
                following.build_ui(root, None)
                root.update()
                control = g._ui
                canvas = control._surface
                def check_bottom_padding():
                    unit_y = canvas.coords(control._unit)[1]
                    assert unit_y == canvas.coords(control._minimum)[1]
                    assert unit_y == canvas.coords(control._maximum)[1]
                    unit_bottom = canvas.bbox(control._unit)[3]
                    # Retain only enough space for the needle at either endpoint.
                    overhang = canvas.winfo_height() - unit_bottom
                    allowance = max(2, control._geometry[2] * 0.022) + 2
                    assert 0 <= overhang <= allowance
                    gap = (following._ui.winfo_rooty()
                           - canvas.winfo_rooty() - unit_bottom)
                    expected = control._apply_widget_scaling(10) + overhang
                    assert abs(gap - expected) <= 1, (gap, expected)
                check_bottom_padding()
                standard_label = ctk.CTkLabel(root, text="Standard", font=g._scaled_font())
                label_font = control._label.cget("font").actual()
                assert label_font == standard_label.cget("font").actual()
                assert control._label.pack_info()["fill"] == "x"
                root.geometry("450x380")
                root.update()
                check_bottom_padding()
                assert control._label.cget("font").actual() == label_font
                standard_label.destroy()
                items = canvas.find_all()
                assert canvas.itemcget(control._caption, "text") == "24.60"
                assert canvas.itemcget(control._unit, "text") == "%"
                def send(value):
                    g.set(value)
                    g.update_ui(g.display_value(g.get()))
                for value, expected in ((79, "79.00"), (79.00, "79.00"),
                                        (79.10, "79.10"), (0, "0.000"),
                                        (-7.10, "-7.100"), (100.53, "100.5"),
                                        (100, "100.0"), (999.94, "999.9"),
                                        (999.99, "1000"), (1000, "1000")):
                    send(value)
                    root.update()
                    assert canvas.itemcget(control._caption, "text") == expected
                send(100.53)
                root.update()
                with patch.object(control._caption_font, "configure") as configure:
                    with patch.object(control._caption_font, "measure") as measure:
                        for value in (100.63, 101.23, 150.05, 999.94):
                            send(value)
                            root.update()
                        configure.assert_not_called()
                        measure.assert_not_called()
                with patch.object(control, "_layout", wraps=control._layout) as layout:
                    with patch.object(canvas, "coords", wraps=canvas.coords) as coords:
                        send(56)
                        root.update()
                        layout.assert_not_called()
                        assert coords.call_count == 3, coords.call_args_list
                assert canvas.find_all() == items
                # Descending tips on the right side must invalidate an area
                # beyond the polygon/hub bounds, including their old positions.
                def check_needle_damage():
                    left, top, right, bottom = canvas.coords(control._needle_damage)
                    points = canvas.coords(control._needle)
                    hub = canvas.coords(control._hub)
                    xs = points[::2] + hub[::2]
                    ys = points[1::2] + hub[1::2]
                    assert left <= min(xs) - 4 and top <= min(ys) - 4
                    assert right >= max(xs) + 4 and bottom >= max(ys) + 4
                    assert canvas.itemcget(control._needle_damage, "fill") == ""
                    assert canvas.itemcget(control._needle_damage, "outline") == ""
                with patch.object(control, "_layout") as layout:
                    for value in range(100, -1, -1):
                        send(value)
                        root.update()
                        check_needle_damage()
                    layout.assert_not_called()
                assert canvas.find_all() == items
                # Height/position notifications must not relayout, remeasure
                # fonts or repack the heading when width and value are stable.
                with patch.object(control, "_layout") as layout:
                    with patch.object(control._caption_font, "measure") as measure:
                        with patch.object(control._label, "configure") as heading:
                            control._draw(no_color_updates=True)
                            control._request_render()
                            root.update()
                            layout.assert_not_called()
                            measure.assert_not_called()
                            heading.assert_not_called()
                # Bursts schedule a single idle callback; only the last value draws.
                for n in range(100):
                    send(n)
                pending = control._render_job
                send(99)
                assert control._render_job == pending
                root.update()
                assert canvas.itemcget(control._caption, "text") == "99.00"
                assert control._render_job is None
                with patch.object(canvas, "itemconfigure") as configure:
                    send(99)
                    root.update()
                    configure.assert_not_called()
                send(100)
                root.update()
                endpoint = canvas.coords(control._needle)
                send(150)
                root.update()
                assert canvas.coords(control._needle) == endpoint
                assert canvas.itemcget(control._caption, "text") == "150.0"
                def check_caption_fits(value):
                    send(value)
                    root.update()
                    text = canvas.itemcget(control._caption, "text")
                    assert g.get() == value
                    assert control._caption_font.measure(text) <= control._caption_width
                    left, top, right, bottom = canvas.bbox(control._caption)
                    cx, cy, radius = control._geometry
                    assert left >= cx - radius * 0.575
                    assert right <= cx + radius * 0.575
                    return text
                rounded = check_caption_fits(56.123456789012345)
                assert len(rounded) < len(str(g.get()))
                assert abs(float(rounded) - g.get()) < 0.1
                for value in (123456789012345, -1.23456789e200, 1.23456789e-200):
                    assert "e" in check_caption_fits(value)
                root.geometry("220x380")
                root.update()
                check_caption_fits(-1.23456789e200)
                root.geometry("450x380")
                root.update()
                check_caption_fits(24.6)
                assert control._caption_font.cget("size") == -control._caption_size
                g.clear()
                g.update_ui(g.display_value(g.get()))
                root.update()
                assert canvas.itemcget(control._needle, "state") == "hidden"
                assert canvas.coords(control._needle_damage) == [0, 0, 0, 0]
                assert canvas.itemcget(control._caption, "text") == ""
                g.configure(bg_color="white", font_color="black", enabled=False,
                            width=450, height=280, label="New")
                g.update_ui(g.display_value(g.get()))
                root.update()
                assert canvas.cget("bg") == "#ffffff"
                assert canvas.itemcget(control._arcs[0], "state") == "disabled"
                assert control._label.cget("text") == "New"
                g.reset()
                g.update_ui(g.display_value(g.get()))
                root.update()
                ctk.set_appearance_mode("Dark")
                ctk.set_widget_scaling(1.5)
                root.geometry("750x500")
                root.update()
                assert canvas.find_all() == items
                assert canvas.itemcget(control._arcs[0], "state") == "normal"
                assert control._render_job is None
                check_bottom_padding()
                check_needle_damage()
                send(10)
                job = control._render_job
                control.destroy()
                assert job not in root.tk.call("after", "info")
                root.destroy()
                print("RENDER_OK")
            """),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if "NO_DISPLAY" in result.stdout:
            self.skipTest("Tk requires a display")
        self.assertIn("RENDER_OK", result.stdout)
