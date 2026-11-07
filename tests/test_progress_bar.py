"""Progress values, process transport, and animated rendering."""

import pickle
import subprocess
import sys
import textwrap
import unittest
from unittest.mock import Mock, patch

from test_widgets import FakeRuntime

from cardtable import Card, Element, ProgressBar
from cardtable.core.closure import Closure


class ProgressBarTest(unittest.TestCase):
    def tearDown(self):
        Closure().close_all()

    def test_values_text_units_and_reset(self):
        bar = ProgressBar(label="Ready", unit=" items", max=200)
        self.assertIsInstance(bar, Element)
        self.assertEqual(bar.get(), 0)
        bar.set(10, "loading")
        self.assertEqual(bar.get(), 10)
        self.assertEqual(
            bar.display_value(bar.get()),
            {"fraction": 0.05, "text": "loading", "caption": "10 items"},
        )
        bar.set(200, "done")
        self.assertEqual(bar.display_value(bar.get())["fraction"], 1)
        bar.value = 50.5
        self.assertEqual(bar.text, "done")
        self.assertEqual(bar.display_value(bar.get())["caption"], "50.5 items")
        bar.set(50, "")
        self.assertEqual(bar.text, "")
        bar.reset()
        self.assertEqual(bar.get(), 0)
        self.assertEqual(bar.text, "Ready")

    def test_default_scale_and_out_of_range_fill(self):
        bar = ProgressBar()
        for value, fraction in ((10, 0.1), (100, 1), (150, 1), (-10, 0)):
            bar.set(value)
            self.assertEqual(bar.get(), value)
            self.assertEqual(bar.display_value(value)["fraction"], fraction)
            self.assertEqual(bar.display_value(value)["caption"], f"{value}%")

    def test_invalid_updates_are_atomic(self):
        bar = ProgressBar()
        bar.set(10, "loading")
        for value, text in (
            (True, "changed"),
            ("10", "changed"),
            (float("nan"), "changed"),
            (float("inf"), "changed"),
            (20, 42),
        ):
            with self.subTest(value=value, text=text):
                with self.assertRaises((ValueError, TypeError)):
                    bar.set(value, text)
                self.assertEqual((bar.get(), bar.text), (10, "loading"))
        for options in (
            {"max": 0},
            {"max": -1},
            {"max": True},
            {"max": "100"},
            {"max": float("inf")},
            {"max": float("nan")},
            {"label": None},
            {"unit": None},
            {"color_0": None},
            {"color_1": 0xFFFFFF},
            {"color_0": "red"},
            {"color_1": "#GG00FF"},
            {"color_0": "#12345678"},
            {"color_1": "#12"},
        ):
            with self.subTest(options=options):
                with self.assertRaises((ValueError, TypeError)):
                    ProgressBar(**options)

    def test_card_transport_and_ui_resources(self):
        runtime = FakeRuntime()
        with Card(0, 0, 4, 3, "Progress", runtime=runtime) as card:
            bar = ProgressBar(
                "Ready", unit="MB", max=200, color_0="#123", color_1="#aBcDeF"
            )
        card.start()
        bar.set(100, "loading")
        self.assertEqual(card.values(), (100,))
        payload = pickle.loads(pickle.dumps(runtime.updates[-1][1]))
        self.assertEqual(
            payload,
            {
                bar.name: {
                    "fraction": 0.5,
                    "text": "loading",
                    "caption": "100MB",
                }
            },
        )
        with patch(
            "cardtable.widgets.elements._progress_bar_control._ProgressBarControl"
        ) as control:
            parent = Mock()
            bar.build_ui(parent, Mock())
            control.assert_called_once_with(
                parent, color_0="#112233", color_1="#ABCDEF", font_scale=1.0
            )
            control.return_value.set.assert_called_with(0.5, "loading", "100MB")
            copied = pickle.loads(pickle.dumps(bar))
            self.assertFalse(hasattr(copied, "_ui"))
            self.assertEqual(copied.get(), 100)
            self.assertEqual(copied.text, "loading")
            self.assertEqual((copied.color_0, copied.color_1), ("#112233", "#ABCDEF"))
            bar.reset()
            bar.update_ui(runtime.updates[-1][1][bar.name])
            control.return_value.set.assert_called_with(0, "Ready", "0MB")

    def test_native_animation_resize_and_cleanup(self):
        # Isolate Tk's global state just as the real UI process does.
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent("""
                import tkinter as tk
                import customtkinter as ctk
                from cardtable import ProgressBar
                from unittest.mock import patch
                from cardtable.widgets.elements._progress_bar_control import (
                    _ProgressBarControl,
                )
                try:
                    root = ctk.CTk()
                except tk.TclError:
                    print("NO_DISPLAY")
                    raise SystemExit(0)
                root.geometry("400x100")
                bar = _ProgressBarControl(root)
                # Construction allocates neither gradient images nor timers.
                assert bar._image is None and bar._palette is None
                assert bar._job is None and bar._render_job is None
                assert len(bar.winfo_children()) == 1
                canvas = bar._surface
                assert len(canvas.find_all()) == 5
                bar.pack(fill="x")
                root.update()
                assert bar._image is None and bar._job is None
                bar.set(0.5, "loading", "10%")
                root.update()
                assert canvas.itemcget(bar._text_item, "text") == "loading"
                assert canvas.itemcget(bar._caption_item, "text") == "10%"
                assert bar._job is not None
                assert bar._image.width() == round(canvas.winfo_width() * 0.5)
                with patch("time.monotonic", return_value=bar._origin):
                    bar._paint()
                assert bar._image.get(0, 5) == (255, 0, 255)
                with patch("time.monotonic", return_value=bar._origin + 1):
                    bar._paint()
                assert bar._image.get(0, 5) == (135, 206, 235)
                # A quarter-period shift moves the same color to the right.
                with patch("time.monotonic", return_value=bar._origin):
                    bar._paint()
                zoom = (canvas.winfo_width() + 255) // 256
                color = bar._image.get(0, 5)
                with patch("time.monotonic", return_value=bar._origin + 0.5):
                    bar._paint()
                assert bar._image.get(64 * zoom, 5) == color
                # Corners are genuinely transparent, including after repaint.
                assert bar._image.transparency_get(0, 0)
                assert bar._image.transparency_get(bar._image.width() - 1, 0)
                assert not bar._image.transparency_get(0, bar._image.height() // 2)
                image = bar._image
                items = canvas.find_all()
                # Updates reuse every item and the image; bursts are coalesced.
                for value in range(1, 100):
                    bar.set(value / 100, "loading", f"{value}%")
                render_job = bar._render_job
                bar.set(0.99, "loading", "99%")
                assert bar._render_job == render_job
                root.update()
                assert bar._image is image and canvas.find_all() == items
                assert bar._image.width() == round(canvas.winfo_width() * 0.99)
                with patch.object(canvas, "itemconfigure") as configure:
                    bar.set(0.99, "loading", "99%")
                    configure.assert_not_called()
                assert bar._render_job is None
                root.geometry("600x100")
                root.update()
                assert bar._image.width() == round(canvas.winfo_width() * 0.99)
                ctk.set_appearance_mode("Dark")
                root.update()
                assert canvas.itemcget(bar._track_item, "fill") == bar._track_color()
                ctk.set_widget_scaling(1.5)
                root.update()
                assert bar._image.height() == 15
                assert bar._image.transparency_get(0, 0)
                assert bar._image.transparency_get(bar._image.width() - 1, 14)
                bar.pack_forget()
                root.update()
                assert bar._job is None
                bar.set(0.5, "hidden", "50%")
                root.update()
                assert bar._job is None
                bar.pack(fill="x")
                root.update()
                assert bar._job is not None
                # The palette is shared by all controls in one interpreter.
                other = _ProgressBarControl(root)
                other.pack(fill="x")
                other.set(1, "done", "100%")
                root.update()
                assert other._palette is bar._palette
                other.destroy()
                root.geometry("600x400")
                colored = ProgressBar(color_0="#123", color_1="#aBcDeF")
                colored.set(100)
                colored.build_ui(root, None)
                root.update()
                custom = colored._ui
                assert custom._palette is not bar._palette
                with patch("time.monotonic", return_value=custom._origin):
                    custom._paint()
                assert custom._image.get(0, 7) == (17, 34, 51)
                with patch("time.monotonic", return_value=custom._origin + 1):
                    custom._paint()
                assert custom._image.get(0, 7) == (171, 205, 239)
                assert custom._image.transparency_get(0, 0)
                custom.destroy()
                bar.set(0, "Ready", "0%")
                assert bar._job is None
                assert canvas.itemcget(bar._fill_item, "state") == "hidden"
                bar.set(1, "done", "100%")
                root.update()
                assert bar._image.width() == canvas.winfo_width()
                job = bar._job
                bar.set(0.5, "closing", "50%")
                render_job = bar._render_job
                bar.destroy()
                pending = root.tk.call("after", "info")
                assert job not in pending and render_job not in pending
                root.update()
                root.destroy()
            """),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if "NO_DISPLAY" in result.stdout:
            self.skipTest("Tk display unavailable")


if __name__ == "__main__":
    unittest.main()
