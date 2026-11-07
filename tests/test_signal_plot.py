"""Signal storage, extrema, viewport, and transport correctness."""

import copy
import pickle
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from cardtable import Card, Entry, SignalPlot, Text
from cardtable.widgets.elements.base import DisplayRequest
from cardtable.widgets.elements.signal_plot._signal_buffer import SignalBuffer
from cardtable.widgets.elements.signal_plot._signal_plot_control import (
    SignalPlotControl,
    clip_segments,
)


class SignalBufferTests(unittest.TestCase):
    def test_random_wraps_match_raw_extrema(self):
        rng = np.random.default_rng(65)
        for capacity in (1, 3, 31, 128, 1001):
            buffer = SignalBuffer(capacity, "float32")
            history = []
            for _ in range(50):
                chunk = rng.normal(size=int(rng.integers(1, 2 * capacity + 1)))
                if len(chunk) == 1:
                    buffer.append(chunk[0])
                else:
                    buffer.extend(chunk)
                history.extend(chunk)
                assert_allclose(buffer.get(), history[-capacity:], rtol=1e-6)
                for width in (1, 3, 17):
                    first = buffer.start + int(rng.integers(0, len(buffer.get())))
                    indices, values = buffer.envelope(first, buffer.count, width)
                    self.assertTrue(np.all(np.diff(indices) >= 0))
                    self.assertLessEqual(len(indices), 4 * width)
                    assert_array_equal(values, buffer.at(indices))
                    raw = buffer.at(np.arange(first, buffer.count))
                    self.assertEqual(np.min(raw), np.min(values))
                    self.assertEqual(np.max(raw), np.max(values))

    def test_each_pixel_preserves_both_extrema_after_wrap(self):
        rng = np.random.default_rng(7)
        buffer = SignalBuffer(10007, "float64")
        buffer.extend(rng.normal(size=19000))
        width = 211
        first, last = buffer.start + 17, buffer.count - 23
        indices, values = buffer.envelope(first, last, width)
        edges = first + np.arange(width + 1) * (last - first) // width
        for i, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
            raw = buffer.at(np.arange(lo, hi))
            self.assertEqual(np.min(raw), np.min(values[4 * i : 4 * i + 4]))
            self.assertEqual(np.max(raw), np.max(values[4 * i : 4 * i + 4]))
            self.assertEqual(indices[4 * i], lo)
            self.assertEqual(indices[4 * i + 3], hi - 1)


class SignalPlotTests(unittest.TestCase):
    def test_exports(self):
        from cardtable.widgets import SignalPlot as WidgetPlot
        from cardtable.widgets.elements import SignalPlot as ElementPlot

        self.assertIs(SignalPlot, WidgetPlot)
        self.assertIs(SignalPlot, ElementPlot)

    def test_aspect_matches_image_api(self):
        self.assertEqual(SignalPlot().aspect, (4, 3))
        plot = SignalPlot(aspect=[16, 9])
        self.assertEqual(plot.aspect, (16, 9))
        with self.assertRaises(TypeError):
            SignalPlot(height=180)

    def test_capacity_counters_replace_empty_reset(self):
        plot = SignalPlot(max_points=3, y_range=(0, 10))
        plot.set([10, 20, 30, 40])
        assert_array_equal(plot.get(), [20, 30, 40])
        self.assertEqual((plot.start_index, plot.sample_count), (1, 4))
        plot.append(50)
        plot.expand([60, 70, 80, 90])
        assert_array_equal(plot.get(), [70, 80, 90])
        self.assertEqual((plot.start_index, plot.sample_count), (6, 9))
        plot.configure(y_range=None)
        revision = plot._revision
        plot.expand([])
        self.assertEqual(plot._revision, revision)
        plot.set([])
        self.assertEqual(plot.sample_count, 0)
        self.assertEqual(len(plot.get()), 0)
        self.assertIsNone(plot.y_range)
        plot.reset()
        self.assertEqual(plot.y_range, (0, 10))

    def test_input_and_output_do_not_alias(self):
        plot = SignalPlot()
        source = np.arange(10, dtype=np.float32)
        plot.set(source)
        source[:] = -5
        result = plot.get()
        result[:] = 100
        assert_array_equal(plot.get(), np.arange(10))
        plot.expand(source)
        source[:] = -10
        assert_array_equal(plot.get()[-10:], np.full(10, -5))

    def test_invalid_updates_are_atomic(self):
        plot = SignalPlot(max_points=10)
        plot.set([1, 2])
        for values, error in (
            ([True], TypeError),
            ([1, False], TypeError),
            ([[1]], TypeError),
            (np.array([1], dtype=object), TypeError),
            ([1j], TypeError),
            (["1"], TypeError),
            (1, TypeError),
            ([np.nan], ValueError),
            ([np.inf], ValueError),
            ([1e100], ValueError),
        ):
            for method in (plot.set, plot.expand):
                with self.subTest(method=method, values=values):
                    revision = plot._revision
                    with self.assertRaises(error):
                        method(values)
                    assert_array_equal(plot.get(), [1, 2])
                    self.assertEqual(plot.sample_count, 2)
                    self.assertEqual(plot._revision, revision)
        for value in (True, [1], "1", 1j):
            with self.assertRaises(TypeError):
                plot.append(value)
        with self.assertRaises(ValueError):
            plot.set([5], y_range=(2, 1))
        assert_array_equal(plot.get(), [1, 2])

    def test_settings_validation_and_reset(self):
        for options, error in (
            ({"sample_rate": 0}, ValueError),
            ({"sample_rate": True}, TypeError),
            ({"max_points": 0}, ValueError),
            ({"max_points": True}, TypeError),
            ({"max_fps": 61}, ValueError),
            ({"max_fps": np.inf}, ValueError),
            ({"follow_window": -1}, ValueError),
            ({"aspect": (4, 0)}, ValueError),
            ({"aspect": (4, -1)}, ValueError),
            ({"aspect": (4, float("inf"))}, ValueError),
            ({"aspect": "4:3"}, TypeError),
            ({"aspect": (4,)}, TypeError),
            ({"aspect": (4, True)}, TypeError),
            ({"x_range": [0, 1]}, TypeError),
            ({"y_range": (1, 1)}, ValueError),
        ):
            with self.subTest(options=options), self.assertRaises(error):
                SignalPlot(**options)
        plot = SignalPlot(x_range=(0, 4), follow_window=2)
        plot.configure(x_range=None, max_fps=60)
        self.assertIsNone(plot.x_range)
        self.assertEqual(plot.follow_window, 2)
        with self.assertRaises(ValueError):
            plot.configure(y_range=(1, 2), max_fps=100)
        self.assertIsNone(plot.y_range)
        plot.reset()
        self.assertEqual(plot.x_range, (0, 4))
        self.assertEqual(plot.max_fps, 30)

    def test_fixed_auto_follow_time_axis(self):
        plot = SignalPlot(sample_rate=2, x_origin=10, max_points=3)
        plot.set([1, 2, 3, 4])
        packet = plot._snapshot(100)
        self.assertEqual(packet["x_range"], (10.5, 11.5))
        plot.configure(follow_window=2)
        self.assertEqual(plot._snapshot(100)["x_range"], (9.5, 11.5))
        plot.configure(x_range=(0, 1))
        packet = plot._snapshot(100)
        self.assertEqual(len(packet["points"]), 0)
        self.assertEqual(packet["y_range"], (-1, 1))
        plot.append(5)
        self.assertEqual(plot._snapshot(100)["x_range"], (0, 1))
        plot.configure(x_range=None)
        self.assertEqual(plot._snapshot(100)["x_range"], (10, 12))

    def test_y_auto_uses_visible_boundary_interpolation(self):
        plot = SignalPlot(dtype="float64", x_range=(0.25, 0.75))
        plot.set([0, 100, -1000])
        packet = plot._snapshot(1)
        self.assertEqual(packet["y_range"], (22.5, 77.5))
        assert_allclose(packet["points"][:, 0], [0, 1])
        plot.configure(x_range=(0.5, 1000.5))
        plot.set(np.r_[0, 100, np.zeros(1000)])
        packet = plot._snapshot(1)
        # The first boundary must interpolate samples 0 and 1, despite LOD.
        self.assertAlmostEqual(packet["points"][0, 1], (50 + 5) / 110)

    def test_snapshot_size_and_peaks(self):
        plot = SignalPlot()
        samples = np.zeros(1_000_000, dtype=np.float32)
        samples[12345], samples[912345] = 100, -100
        plot.set(samples)
        packet = plot._snapshot(1000)
        self.assertLessEqual(len(packet["points"]), 4002)
        self.assertEqual(packet["y_range"], (-110, 110))
        self.assertLess(len(pickle.dumps(packet)), 70000)

    def test_empty_constant_and_extreme_ranges_are_finite(self):
        for options, samples in (
            ({}, []),
            ({}, [0]),
            ({}, [2, 2]),
            ({"dtype": "float64"}, [-1.79e308, 1.79e308]),
            ({"sample_rate": 5e-324}, [1, 2]),
            ({"x_origin": 1.79e308}, [1, 2]),
            ({"x_range": (-1.79e308, 1.79e308)}, [1, 2]),
            ({"dtype": "float64", "y_range": (-1e-300, 1e-300)}, [-1e308, 1e308]),
        ):
            with self.subTest(options=options):
                plot = SignalPlot(**options)
                plot.set(samples)
                with np.errstate(all="raise"):
                    packet = plot._snapshot(100)
                for key in ("x_range", "y_range", "points"):
                    self.assertTrue(np.isfinite(packet[key]).all())
                self.assertLess(*packet["x_range"])
                self.assertLess(*packet["y_range"])

    def test_concurrent_append_chunks_and_get(self):
        plot = SignalPlot(max_points=10000)

        def add(worker):
            for _ in range(50):
                plot.append(worker)
                plot.expand([worker] * 5)
                plot.get()

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(add, range(4)))
        result = plot.get()
        self.assertEqual(plot.sample_count, 1200)
        for worker in range(4):
            self.assertEqual(np.count_nonzero(result == worker), 300)

    def test_copy_and_pickle_do_not_transfer_raw_recording(self):
        plot = SignalPlot(max_points=1_000_000)
        plot.set(np.ones(1_000_000, dtype=np.float32))
        self.assertLess(len(pickle.dumps(plot)), 1000)
        for restored in (
            copy.copy(plot),
            copy.deepcopy(plot),
            pickle.loads(pickle.dumps(plot)),
        ):
            self.assertEqual(restored.name, plot.name)
            self.assertEqual(restored.sample_count, 0)
            self.assertIsNone(restored._buffer.data)
            self.assertIsNone(restored._owner)
        self.assertEqual(plot.sample_count, 1_000_000)

    def test_card_values_and_pull_requests_never_become_input_events(self):
        runtime = Mock()
        callback = Mock()
        with Card(0, 0, 4, 4, "Signal", runtime=runtime) as card:
            plot = SignalPlot(max_points=10)
            text = Text()
            Entry(on_input=callback)
        card.start()
        runtime.update.reset_mock()
        with patch.object(plot, "display_value", wraps=plot.display_value) as display:
            for i in range(20):
                plot.append(i)
            display.assert_not_called()
        runtime.update.assert_not_called()
        assert_array_equal(card.values()[0], np.arange(10, 20))
        card._receive_input({plot.name: DisplayRequest(200, -1, 1)})
        packet = runtime.update.call_args.args[1][plot.name]
        self.assertEqual(packet["revision"], plot._revision)
        self.assertEqual(packet["width"], 200)
        self.assertEqual(packet["serial"], 1)
        card._receive_input({plot.name: DisplayRequest(200, plot._revision, 2)})
        self.assertTrue(runtime.update.call_args.args[1][plot.name]["unchanged"])
        callback.assert_not_called()
        self.assertEqual(text.get(), "")
        card.stop()


class SignalRendererTests(unittest.TestCase):
    def test_clipping_preserves_intersections_and_hidden_gaps(self):
        points = np.array([[0, -1], [0.25, 2], [0.5, 2], [0.75, -1], [1, 0.5]])
        clipped = clip_segments(points)
        self.assertEqual(len(clipped), 3)  # entirely outside middle segment omitted
        self.assertTrue(np.all((clipped[:, [1, 3]] >= 0) & (clipped[:, [1, 3]] <= 1)))
        assert_allclose(clipped[0], [1 / 12, 0, 1 / 6, 1])
        extreme = clip_segments(np.array([[0, -1e308], [1, 1e308]]))
        assert_allclose(extreme, [[0.5, 0, 0.5, 1]])

    def renderer(self):
        renderer = object.__new__(SignalPlotControl)
        renderer._canvas = Mock()
        renderer._canvas.winfo_width.return_value = 200
        renderer._canvas.winfo_ismapped.return_value = True
        renderer._canvas.after.return_value = "timer"
        renderer._destroyed = False
        renderer._token = None
        renderer._pending = renderer._packet = None
        renderer._fps = 30
        renderer._revision = -1
        renderer._serial = 0
        renderer._waiting = None
        renderer._request_width = None
        renderer._last_draw = -100
        renderer._emit = Mock()
        renderer._draw = Mock()
        return renderer

    def test_only_one_request_outstanding_and_resizing_forces_new_snapshot(self):
        renderer = self.renderer()
        renderer._tick()
        renderer._tick()
        renderer._emit.assert_called_once_with(DisplayRequest(200, -1, 1))
        plot = SignalPlot()
        plot.set([1, 2])
        packet = plot._display_request(DisplayRequest(200, -1, 1))
        renderer.update(packet)
        self.assertIsNone(renderer._waiting)
        renderer._tick()
        self.assertEqual(renderer._draw.call_count, 1)
        self.assertEqual(renderer._emit.call_args.args[0].revision, plot._revision)
        renderer.update(dict(unchanged=True, serial=2, max_fps=30))
        renderer._canvas.winfo_width.return_value = 300
        renderer._tick()
        self.assertEqual(renderer._emit.call_args.args[0], DisplayRequest(300, -1, 3))
        renderer.update({**packet, "serial": 2})
        self.assertIsNone(renderer._pending)

    def test_snapshots_do_not_reveal_hidden_card(self):
        signal = SignalPlot()
        signal._ui = Mock()
        text = Text()
        text._ui = Mock()
        ui = object.__new__(Card)
        ui._ui_elements = {signal.name: signal, text.name: text}
        self.assertFalse(ui._update_ui({signal.name: signal.display_value(None)}))
        self.assertTrue(
            ui._update_ui({text.name: {"text": "changed", "mode": "plain"}})
        )

    def test_start_and_restart_send_current_recording(self):
        runtime = Mock()
        with Card(0, 0, 4, 4, "Current", runtime=runtime) as card:
            signal = SignalPlot()
        signal.set([1, 2, 3])
        card.start()
        packet = runtime.update.call_args.args[1][signal.name]
        self.assertEqual(packet["revision"], signal._revision)
        self.assertEqual(len(packet["points"]), 3)
        card.stop()
        signal.set([4, 5])
        card.start()
        packet = runtime.update.call_args.args[1][signal.name]
        self.assertEqual(packet["revision"], signal._revision)
        self.assertEqual(len(packet["points"]), 2)
        card.stop()

    def test_resize_preserves_aspect_and_repaints_existing_samples(self):
        renderer = self.renderer()
        renderer._aspect = (4, 1)
        renderer._canvas.winfo_reqheight.return_value = 100
        renderer._packet = {"width": 800}
        renderer._resize(Mock(width=800))
        renderer._canvas.configure.assert_called_once_with(height=200)
        self.assertIs(renderer._pending, renderer._packet)
        renderer._canvas.configure.reset_mock()
        renderer._canvas.winfo_reqheight.return_value = 200
        renderer._resize(Mock(width=800))
        renderer._canvas.configure.assert_not_called()

    def test_hidden_and_destroyed_stop_timers(self):
        renderer = self.renderer()
        renderer._canvas.winfo_ismapped.return_value = False
        renderer._tick()
        renderer._emit.assert_not_called()
        renderer._canvas.after.assert_not_called()
        renderer._token = "timer"
        renderer._destroy(Mock(widget=renderer._canvas))
        renderer._canvas.after_cancel.assert_called_once_with("timer")
        self.assertTrue(renderer._destroyed)
