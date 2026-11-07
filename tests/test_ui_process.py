import subprocess
import sys
import tkinter as tk
import unittest
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock, patch

import customtkinter as ctk

from cardtable.widgets._ui_process import (
    _STATUS_BAR_HEIGHT,
    _bind_input_guard,
    _bind_panel_activation,
    run_ui_process,
)
from cardtable.widgets.deck import _DeckSettings
from cardtable.widgets.theme import TITLE_BG_COLOR


class WindowHeightTest(unittest.TestCase):
    def run_host(
        self, scenario, *, scale=1, settings=_DeckSettings(), expected_error=None,
        prepare=None,
    ):
        root = Mock()
        root.attributes.return_value = 0
        root.winfo_screenheight.return_value = 1000
        root.winfo_rooty.return_value = 100
        root._reverse_window_scaling.side_effect = lambda value: value / scale
        commands = Queue()
        events = Queue()
        callbacks = {}
        frames = []
        root.status_labels = []
        root.usage_sampler = Mock()
        root.usage_sampler.sample.return_value = "CPU:12%, Mem.:1.20GB"
        root.ui = Mock()
        root.ui._button_definitions = {}
        root.ui._buttons = {}

        def make_label(*args, **kwargs):
            label = Mock()
            if args[0] is root.status_bar:
                root.status_labels.append(label)
            else:
                frames.append(label)
            return label

        def after(delay, callback):
            callbacks[callback.__name__] = callback
            return len(callbacks)

        def make_frame(*args, **kwargs):
            frame = Mock()
            if kwargs.get("height") == _STATUS_BAR_HEIGHT:
                root.status_bar = frame
            else:
                frames.append(frame)
            return frame

        def make_popup(*args, **kwargs):
            window = Mock()
            window.winfo_screenwidth.return_value = 1920
            window.winfo_screenheight.return_value = 1080
            window._reverse_window_scaling.side_effect = lambda value: value / scale
            popups.append(window)
            return window

        popups = []
        root.popup_windows = popups

        def send(command_type, widget_id="card", **kwargs):
            commands.put({"type": command_type, "widget_id": widget_id, **kwargs})
            callbacks["drain_commands"]()

        def create(widget_id="card", geometry=None, *, name=None, **options):
            if geometry is None:
                geometry = (
                    (0, 0, 4, 4)
                    if settings.geometry_unit == "grid"
                    else (0, 0, 400, 320)
                )
            send(
                "create",
                widget_id,
                widget_class="test:Card",
                name=name,
                options={"geometry": geometry, **options},
            )

        def bind_activation(frame, callback):
            frame.activate = callback

        root.after.side_effect = after
        root.mainloop.side_effect = lambda: scenario(root, send, create, frames)
        ready = Mock()
        if prepare is not None:
            prepare(root, ready)
        with (
            patch.object(ctk, "CTk", return_value=root),
            patch.object(ctk, "CTkFrame", side_effect=make_frame),
            patch.object(ctk, "CTkLabel", side_effect=make_label),
            patch(
                "cardtable.widgets._status_text.StatusText", side_effect=make_label
            ),
            patch.object(ctk, "CTkFont"),
            patch.object(ctk, "CTkToplevel", side_effect=make_popup),
            patch(
                "cardtable.widgets._ui_process.ProcessUsage",
                return_value=root.usage_sampler,
            ),
            patch(
                "cardtable.widgets._ui_process._resolve_class",
                return_value=Mock(_create_ui=Mock(return_value=root.ui)),
            ),
            patch(
                "cardtable.widgets._ui_process._bind_panel_activation",
                side_effect=bind_activation,
            ),
            patch("cardtable.widgets._ui_process._bind_input_guard"),
            patch("cardtable.widgets._ui_process.apply_window_icon") as icon,
        ):
            run_ui_process(commands, events, ready, settings)
        icon.assert_any_call(root, default=True)
        for window in popups:
            icon.assert_any_call(window)
        errors = [event for event in events.queue if "error" in event["type"]]
        if expected_error is None:
            self.assertEqual(errors, [])
        else:
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0]["type"], "host_error")
            self.assertIn(expected_error, errors[0]["message"])
        return list(events.queue)

    def test_status_bar_starts_empty_and_tracks_window_width(self):
        def scenario(root, send, create, frames):
            create()
            root.status_bar.place.assert_called_once_with(
                relx=0, rely=1, relwidth=1, anchor="sw"
            )
            cards, layout, usage = root.status_labels
            usage.configure.assert_called_with(text="CPU:12%, Mem.:1.20GB |")
            cards.configure.assert_not_called()
            layout.configure.assert_called_with(text="427 px | 4/12 cols")
            create("second")
            cards.configure.assert_not_called()
            send("hide", "second")
            cards.configure.assert_not_called()
            configure = root.bind.call_args.args[1]
            configure(SimpleNamespace(widget=root, width=640, height=344))
            layout.configure.assert_called_with(text="640 px | 4/12 cols")
            root.geometry.assert_called_with("640x504")

        self.run_host(scenario)

    def test_process_usage_updates_every_second_without_card_operations(self):
        def scenario(root, send, create, frames):
            usage = root.status_labels[2]
            scheduled = [
                call.args for call in root.after.call_args_list
                if call.args[1].__name__ == "update_process_usage"
            ]
            self.assertEqual(len(scheduled), 1)
            delay, callback = scheduled[0]
            self.assertEqual(delay, 1000)
            root.usage_sampler.sample.return_value = "CPU:25%, Mem.:2.30GB"
            callback()
            usage.configure.assert_called_with(text="CPU:25%, Mem.:2.30GB |")
            root.after.assert_called_with(1000, callback)

        self.run_host(scenario)

    def test_shutdown_cancels_latest_usage_timer_before_destroy(self):
        def scenario(root, send, create, frames):
            callback = next(
                call.args[1] for call in root.after.call_args_list
                if call.args[1].__name__ == "update_process_usage"
            )
            callback()
            # The fake scheduler returns the number of distinct callback names.
            token = 2
            root.destroy.side_effect = (
                lambda: root.after_cancel.assert_called_with(token)
            )
            send("shutdown")
            calls = root.usage_sampler.sample.call_count
            callback()  # A stale callback must neither sample nor reschedule.
            self.assertEqual(root.usage_sampler.sample.call_count, calls)
            root.after.reset_mock()
            callback()
            root.after.assert_not_called()

        self.run_host(scenario)

    def test_usage_timer_is_cancelled_when_mainloop_exits_or_raises(self):
        for failure in (False, True):
            with self.subTest(failure=failure):
                captured = []

                def scenario(root, send, create, frames):
                    captured.append(root)
                    if failure:
                        raise RuntimeError("mainloop failed")

                self.run_host(
                    scenario, expected_error="mainloop failed" if failure else None
                )
                captured[0].after_cancel.assert_called_once_with(1)

    def test_window_close_followed_by_shutdown_stops_usage_timer(self):
        def scenario(root, send, create, frames):
            create()
            close = root.protocol.call_args.args[1]
            close()
            root.withdraw.assert_called()
            # Closing requests main-process shutdown; it does not wait for it.
            root.usage_sampler.sample.assert_called_once()
            send("shutdown")
            root.after_cancel.assert_called_with(1)

        events = self.run_host(scenario)
        self.assertTrue(any(event["type"] == "close_requested" for event in events))

    def test_startup_failure_cancels_usage_timer_and_unblocks_parent(self):
        captured = []

        def prepare(root, ready):
            captured.append((root, ready))
            root.protocol.side_effect = RuntimeError("protocol setup failed")

        self.run_host(
            Mock(), prepare=prepare, expected_error="protocol setup failed"
        )
        root, ready = captured[0]
        ready.set.assert_called_once()
        root.mainloop.assert_not_called()
        root.after_cancel.assert_called_once_with(1)

    def test_usage_cleanup_tolerates_already_destroyed_tk(self):
        def scenario(root, send, create, frames):
            root.after_cancel.side_effect = tk.TclError("interpreter destroyed")
            send("shutdown")

        self.run_host(scenario)

    def test_status_message_is_overwritten_and_survives_card_operations(self):
        def scenario(root, send, create, frames):
            create()
            message = root.status_labels[0]
            send("status_text", text="Working")
            message.configure.assert_called_with(text="Working")
            send("status_text", text="Done")
            message.configure.assert_called_with(text="Done")
            message.configure.reset_mock()
            frames[0].activate()
            send("hide")
            send("show")
            message.configure.assert_not_called()
            send("status_text", text="")
            message.configure.assert_called_with(text="")

        self.run_host(scenario)

    def test_status_bar_shows_last_operated_card_and_live_geometry(self):
        def scenario(root, send, create, frames):
            create(name="First")
            first = frames[0]
            next_panel = len(frames)
            create("second", name="Second")
            second = frames[next_panel]
            status = root.status_labels[1]
            first.activate()
            status.configure.assert_called_with(
                text="First  (0, 0, 4, 4)   |   427 px | 4/12 cols"
            )
            second.activate()
            status.configure.assert_called_with(
                text="Second  (0, 0, 4, 4)   |   427 px | 4/12 cols"
            )
            title = frames[next_panel + 1]
            bindings = {c.args[0]: c.args[1] for c in title.bind.call_args_list}
            target = Mock()
            bindings["<ButtonPress-1>"](
                SimpleNamespace(widget=target, x_root=0, y_root=0)
            )
            bindings["<B1-Motion>"](SimpleNamespace(x_root=0, y_root=80))
            status.configure.assert_called_with(
                text="Second  (0, 1, 4, 4)   |   427 px | 4/12 cols"
            )
            send("hide", "second")
            status.configure.assert_called_with(text="427 px | 4/12 cols")
            first.activate()
            send("destroy")
            status.configure.assert_called_with(text="1 px | 0/12 cols")

        self.run_host(scenario)

    def test_popup_is_centered_and_excluded_from_deck_layout(self):
        for scale in (1, 2):
            with self.subTest(scale=scale):

                def scenario(root, send, create, frames):
                    create()
                    root.geometry.reset_mock()
                    create("popup", (0, 0, 480, 240), popup=True)
                    window = root.popup_windows[0]
                    x = round((1920 / scale - 480) / 2)
                    y = round((1080 / scale - 240) / 2)
                    window.geometry.assert_called_with(f"480x240+{x}+{y}")
                    window.deiconify.assert_called_once()
                    root.geometry.assert_not_called()
                    # Deck hide/show/resize paths must not place popup windows.
                    send("hide", "popup")
                    window.withdraw.assert_called()
                    send("show", "popup")
                    self.assertEqual(window.deiconify.call_count, 2)
                    window.place.assert_not_called()
                    send("destroy", "popup")
                    window.destroy.assert_called_once()
                    root.geometry.assert_called_with("400x344")

                self.run_host(
                    scenario, scale=scale, settings=_DeckSettings(geometry_unit="px")
                )

    def test_popup_close_and_escape_send_targeted_cancellation(self):
        def scenario(root, send, create, frames):
            create("popup", popup=True)
            window = root.popup_windows[0]
            self.assertEqual(window.protocol.call_args.args[0], "WM_DELETE_WINDOW")
            window.protocol.call_args.args[1]()
            self.assertEqual(window.bind.call_args.args[0], "<Escape>")
            window.bind.call_args.args[1](Mock())
            self.assertEqual(window.withdraw.call_count, 3)
            root.deiconify.assert_not_called()

        events = self.run_host(scenario)
        closes = [event for event in events if event["type"] == "close_requested"]
        self.assertEqual(len(closes), 2)
        self.assertTrue(all(event["widget_id"] == "popup" for event in closes))

    def test_popup_default_focus_enter_and_disabled_close(self):
        from cardtable.widgets.elements.button import _BtnPressed
        from cardtable.widgets.elements.result_button import FalseBtn

        button = FalseBtn("No")

        def scenario(root, send, create, frames):
            root.ui._button_definitions = {button.id: button}
            control = Mock()
            root.ui._buttons = {button.id: control}
            create("popup", popup=True, popup_default=False,
                   popup_close_enabled=False)
            window = root.popup_windows[0]
            window.attributes.assert_called_with("-topmost", True)
            window.after_idle.call_args.args[0]()
            control.focus_set.assert_called_once()
            bindings = {c.args[0]: c.args[1] for c in window.bind.call_args_list}
            window.protocol.call_args.args[1]()
            bindings["<Escape>"](Mock())
            window.withdraw.assert_called_once()  # Initial construction only.
            bindings["<Return>"](Mock())
            button.state = "disabled"
            bindings["<KP_Enter>"](Mock())

        events = self.run_host(scenario)
        self.assertFalse(any(e["type"] == "close_requested" for e in events))
        inputs = [e["payload"] for e in events if e["type"] == "input"]
        self.assertEqual(inputs, [_BtnPressed(button.id)])

    def test_deck_disable_blocks_window_close_and_keeps_updates_running(self):
        def scenario(root, send, create, frames):
            create()
            close = root.protocol.call_args.args[1]
            send("deck_enabled", enabled=False)
            root.withdraw.reset_mock()
            close()
            root.withdraw.assert_not_called()
            send("update", payload={"value": 5})
            root.ui._update_ui.assert_called_once_with({"value": 5})
            send("deck_enabled", enabled=True)
            close()
            root.withdraw.assert_called_once()

        events = self.run_host(scenario)
        self.assertEqual(len([e for e in events if e["type"] == "close_requested"]), 1)

    def test_height_tracks_lowest_visible_card_and_can_shrink(self):
        def scenario(root, send, create, frames):
            create()
            root.geometry.assert_called_with("400x344")
            create("lower", (0, 500, 400, 300))
            root.geometry.assert_called_with("400x824")
            send("hide", "lower")
            root.geometry.assert_called_with("400x344")
            send("show", "lower")
            root.geometry.assert_called_with("400x824")
            send("destroy", "lower")
            root.geometry.assert_called_with("400x344")
            send("hide")
            root.withdraw.assert_called()
            create("hidden", (0, 0, 400, 1000), show_on_create=False)
            send("show")
            root.geometry.assert_called_with("400x344")

        self.run_host(scenario, settings=_DeckSettings(geometry_unit="px"))

    def test_width_tracks_rightmost_visible_card(self):
        def scenario(root, send, create, frames):
            create()
            root.geometry.assert_called_with("427x344")
            create("right", (8, 0, 4, 4))
            root.geometry.assert_called_with("1280x344")
            root.status_labels[1].configure.assert_called_with(text="1280 px | 12/12 cols")
            send("hide", "right")
            root.geometry.assert_called_with("427x344")
            root.status_labels[1].configure.assert_called_with(text="427 px | 4/12 cols")
            send("show", "right")
            root.geometry.assert_called_with("1280x344")
            send("destroy", "right")
            root.geometry.assert_called_with("427x344")

        self.run_host(scenario)

    def test_width_and_height_changes_refit_without_configure_loop(self):
        def scenario(root, send, create, frames):
            create()
            configure = root.bind.call_args.args[1]
            self.assertEqual(root.bind.call_args.kwargs, {"add": "+"})
            for width, height, expected in (
                (640, 320, 480),
                (1600, 160, 1200),
                (1600, 900, 1200),
            ):
                configure(SimpleNamespace(widget=root, width=width, height=height))
                expected += _STATUS_BAR_HEIGHT
                root.geometry.assert_called_with(f"{width}x{expected}")
                root.minsize.assert_called_with(1, expected)
                root.geometry.reset_mock()
                configure(SimpleNamespace(widget=root, width=width, height=expected))
                root.geometry.assert_not_called()
            configure(SimpleNamespace(widget=Mock(), width=100, height=100))
            root.geometry.assert_not_called()

        self.run_host(scenario)

    def test_fullscreen_relayouts_cards_without_refitting_window(self):
        def scenario(root, send, create, frames):
            create(geometry=(0, 0, 12, 4))
            configure = root.bind.call_args.args[1]
            root.attributes.return_value = 1
            root.geometry.reset_mock()
            root.minsize.reset_mock()
            configure(SimpleNamespace(widget=root, width=1600, height=900))
            frames[0].configure.assert_called_with(width=1596, height=396)
            frames[0].place.assert_called_with(x=2, y=2)
            # Visibility changes also refit through the same path.
            create("second")
            send("hide", "second")
            send("show", "second")
            send("destroy", "second")
            root.geometry.assert_not_called()
            root.minsize.assert_not_called()

            root.attributes.return_value = 0
            configure(SimpleNamespace(widget=root, width=1280, height=900))
            root.geometry.assert_called_with("1280x344")
            root.minsize.assert_called_with(1, 344)

        self.run_host(scenario)

    def test_drag_updates_window_height_only_after_release(self):
        def scenario(root, send, create, frames):
            create()
            title_bindings = {
                call.args[0]: call.args[1] for call in frames[1].bind.call_args_list
            }
            target = Mock()
            target.grab_current.return_value = target
            root.geometry.reset_mock()
            title_bindings["<ButtonPress-1>"](
                SimpleNamespace(widget=target, x_root=0, y_root=0)
            )
            target.grab_set.assert_called_once()
            title_bindings["<B1-Motion>"](SimpleNamespace(x_root=0, y_root=160))
            root.geometry.assert_not_called()
            title_bindings["<ButtonRelease-1>"](SimpleNamespace(x_root=0, y_root=160))
            target.grab_release.assert_called_once()
            root.geometry.assert_called_with("427x504")
            root.geometry.reset_mock()
            title_bindings["<ButtonPress-1>"](
                SimpleNamespace(widget=target, x_root=0, y_root=160)
            )
            title_bindings["<B1-Motion>"](SimpleNamespace(x_root=0, y_root=0))
            root.geometry.assert_not_called()
            title_bindings["<ButtonRelease-1>"](SimpleNamespace(x_root=0, y_root=0))
            root.geometry.assert_called_with("427x344")
            handle_bindings = {
                call.args[0]: call.args[1] for call in frames[-1].bind.call_args_list
            }
            root.geometry.reset_mock()
            handle_bindings["<ButtonPress-1>"](
                SimpleNamespace(widget=target, x_root=0, y_root=0)
            )
            handle_bindings["<B1-Motion>"](SimpleNamespace(x_root=0, y_root=80))
            root.geometry.assert_not_called()
            handle_bindings["<ButtonRelease-1>"](SimpleNamespace(x_root=0, y_root=80))
            root.geometry.assert_called_with("427x424")

        self.run_host(scenario)

    def test_drag_commit_clamps_bottom_to_screen_in_logical_units(self):
        for mode, unit, geometry, scale, expected in (
            ("move", "grid", (0, 0, 4, 4), 1, (0, 6, 4, 4)),
            ("resize", "grid", (0, 2, 4, 4), 1, (0, 2, 4, 8)),
            ("resize", "grid", (0, 0, 4, 4), 2, (0, 0, 4, 5)),
            ("move", "px", (20, 100, 400, 300), 1, (20, 576, 400, 300)),
            ("resize", "px", (20, 100, 400, 300), 1, (20, 100, 400, 776)),
        ):
            with self.subTest(mode=mode, unit=unit, scale=scale):

                def scenario(root, send, create, frames):
                    create(geometry=geometry)
                    target = frames[1] if mode == "move" else frames[-1]
                    bindings = {
                        call.args[0]: call.args[1]
                        for call in target.bind.call_args_list
                    }
                    root.geometry.reset_mock()
                    bindings["<ButtonPress-1>"](
                        SimpleNamespace(widget=target, x_root=0, y_root=0)
                    )
                    bindings["<B1-Motion>"](SimpleNamespace(x_root=0, y_root=2000))
                    root.geometry.assert_not_called()
                    bindings["<ButtonRelease-1>"](
                        SimpleNamespace(x_root=0, y_root=2000)
                    )
                    bottom = (
                        (expected[1] + expected[3]) * 80
                        if unit == "grid"
                        else expected[1] + expected[3]
                    )
                    root.geometry.assert_called_with(
                        f"{427 if unit == 'grid' else 420}x{bottom + _STATUS_BAR_HEIGHT}"
                    )

                events = self.run_host(
                    scenario, scale=scale, settings=_DeckSettings(geometry_unit=unit)
                )
                geometries = [e["geometry"] for e in events if e["type"] == "geometry"]
                self.assertEqual(geometries[-1], expected)

    def test_hiding_or_destroying_dragged_card_releases_capture(self):
        for command_type in ("hide", "destroy"):
            with self.subTest(command_type=command_type):

                def scenario(root, send, create, frames):
                    create()
                    press = frames[1].bind.call_args_list[0].args[1]
                    target = Mock()
                    target.grab_current.return_value = target
                    press(SimpleNamespace(widget=target, x_root=0, y_root=0))
                    send(command_type)
                    target.grab_release.assert_called_once()

                self.run_host(scenario)

    def test_configure_uses_logical_dimensions_on_scaled_displays(self):
        def scenario(root, send, create, frames):
            create()
            configure = root.bind.call_args.args[1]
            configure(SimpleNamespace(widget=root, width=1200, height=600))
            root.geometry.assert_called_with("600x474")

        self.run_host(scenario, scale=2, settings=_DeckSettings(window_width=1200))

    def test_shared_grid_settings_control_all_cards_and_dragging(self):
        def scenario(root, send, create, frames):
            create(geometry=(0, 0, 4, 4))
            root.geometry.assert_called_with("400x224")
            frames[0].place.assert_called_with(x=2, y=2)
            next_panel = len(frames)
            create("right", geometry=(12, 0, 4, 4))
            root.geometry.assert_called_with("1600x224")
            frames[next_panel].place.assert_called_with(x=1202, y=2)
            bindings = {
                call.args[0]: call.args[1]
                for call in frames[next_panel + 1].bind.call_args_list
            }
            target = Mock()
            target.grab_current.return_value = target
            bindings["<ButtonPress-1>"](
                SimpleNamespace(widget=target, x_root=0, y_root=0)
            )
            bindings["<B1-Motion>"](SimpleNamespace(x_root=-100, y_root=50))
            bindings["<ButtonRelease-1>"](SimpleNamespace(x_root=-100, y_root=50))
            root.geometry.assert_called_with("1500x274")

        events = self.run_host(
            scenario, settings=_DeckSettings("grid", 16, (2, 1), 1600)
        )
        geometries = [
            e["geometry"]
            for e in events
            if e["type"] == "geometry" and e["widget_id"] == "right"
        ]
        self.assertEqual(geometries[-1], (11, 1, 4, 4))


class NativePanelDragTest(unittest.TestCase):
    def test_title_drag_keeps_capture_outside_bar_until_release(self):
        # Match the UI host's separate process; CustomTkinter keeps global Tk
        # state that can outlive windows created by other tests.
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, unittest; sys.path.insert(0, 'tests'); "
                "from test_ui_process import NativePanelDragTest; "
                "result = unittest.TextTestRunner().run(unittest.TestSuite(["
                "NativePanelDragTest('check_native_drag')])); "
                "sys.exit(not result.wasSuccessful())",
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if "skipped=1" in result.stderr:
            self.skipTest("Tk display unavailable in UI host process")

    def check_native_drag(self):
        try:
            root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        commands, events = Queue(), Queue()
        failures = []
        commands.put(
            dict(
                type="create",
                widget_id="card",
                widget_class="test:Card",
                name=None,
                options=dict(geometry=(0, 0, 4, 4)),
            )
        )

        def check_drag():
            try:
                root.update_idletasks()
                self.assertEqual(
                    [event for event in events.queue if "error" in event["type"]],
                    [],
                )
                panel = next(
                    child for child in root.winfo_children()
                    if isinstance(child, ctk.CTkFrame)
                    and child.cget("height") != _STATUS_BAR_HEIGHT
                )
                title = next(
                    child
                    for child in panel.winfo_children()
                    if child.cget("fg_color") == TITLE_BG_COLOR
                )
                self.assertEqual(title.winfo_height(), 8)
                # Use the widget actually hit at every row, including the lower
                # edge, rather than sending every press directly to the Canvas.
                for y in range(title.winfo_height()):
                    hit = root.winfo_containing(
                        title.winfo_rootx() + 20, title.winfo_rooty() + y
                    )
                    self.assertIn(hit, (title, title._canvas))
                    hit.event_generate("<ButtonPress-1>", x=20, y=y)
                    self.assertIs(root.grab_current(), hit)
                    hit.event_generate("<ButtonRelease-1>", x=20, y=y)
                    self.assertIsNone(root.grab_current())
                # Verify the outer frame's binding as well as its Canvas.
                title.event_generate("<ButtonPress-1>", x=20, y=7)
                self.assertIs(root.grab_current(), title)
                title.event_generate("<ButtonRelease-1>", x=20, y=7)
                target = title._canvas
                start_x = target.winfo_rootx() + 20
                start_y = target.winfo_rooty() + 3
                target.event_generate("<ButtonPress-1>", x=20, y=3)
                self.assertIs(root.grab_current(), target)
                self.assertEqual(target.grab_status(), "local")
                original_height = root.winfo_height()
                # Cross the thin bar and snap multiple grid rows while
                # still holding the button, then reverse direction.
                target.event_generate("<Leave>")
                for dy in (150, 225, 75):
                    target.event_generate(
                        "<B1-Motion>",
                        x=20,
                        y=3,
                        rootx=start_x,
                        rooty=start_y + dy,
                    )
                    root.update_idletasks()
                    self.assertEqual(panel.winfo_y(), dy + 2)
                    self.assertIs(root.grab_current(), target)
                    self.assertEqual(root.winfo_height(), original_height)
                target.event_generate(
                    "<ButtonRelease-1>",
                    x=20,
                    y=3,
                    rootx=start_x,
                    rooty=start_y + 75,
                )
                self.assertIsNone(root.grab_current())
                self.assertEqual(root.winfo_height(), 375 + _STATUS_BAR_HEIGHT)
                geometries = [
                    event["geometry"]
                    for event in events.queue
                    if event["type"] == "geometry"
                ]
                self.assertEqual(geometries[-1], (0, 1, 4, 4))
                # Commit a resize far beyond the display, then shrink it again
                # using the handle that must remain inside the window.
                handle = panel.winfo_children()[-1]
                for dy in (10000, -75):
                    handle.event_generate(
                        "<ButtonPress-1>", x=0, y=0, rootx=300, rooty=300
                    )
                    handle.event_generate(
                        "<B1-Motion>", x=0, y=0, rootx=300, rooty=300 + dy
                    )
                    handle.event_generate(
                        "<ButtonRelease-1>", x=0, y=0, rootx=300, rooty=300 + dy
                    )
                    self.assertLessEqual(
                        root.winfo_rooty() + root.winfo_height(),
                        root.winfo_screenheight(),
                    )
                    self.assertLessEqual(
                        panel.winfo_y() + panel.winfo_height(), root.winfo_height()
                    )
            except Exception as error:
                failures.append(error)
            finally:
                commands.put(dict(type="shutdown"))

        root.after(150, check_drag)
        with (
            patch.object(ctk, "CTk", return_value=root),
            patch(
                "cardtable.widgets._ui_process._resolve_class",
                return_value=Mock(),
            ),
        ):
            run_ui_process(commands, events, Mock(), _DeckSettings(window_width=1200))
        if failures:
            raise failures[0]
        errors = [event for event in events.queue if "error" in event["type"]]
        self.assertEqual(errors, [])


class PanelActivationTest(unittest.TestCase):
    def test_input_guard_blocks_descendants_and_preserves_control_state(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        self.addCleanup(root.destroy)
        frame = tk.Frame(root)
        frame.pack()
        entry = tk.Entry(frame)
        entry.pack()
        disabled = tk.Entry(frame, state="disabled")
        disabled.pack()
        blocked = [False]
        pressed = Mock()
        entry.bind("<ButtonPress-1>", pressed)
        _bind_input_guard(frame, lambda: blocked[0])
        root.update()
        entry.event_generate("<ButtonPress-1>", x=1, y=1)
        pressed.assert_called_once()
        blocked[0] = True
        entry.event_generate("<ButtonPress-1>", x=1, y=1)
        self.assertEqual(pressed.call_count, 1)
        blocked[0] = False
        _bind_input_guard(frame, lambda: blocked[0])  # Safe after display updates.
        entry.event_generate("<ButtonPress-1>", x=1, y=1)
        self.assertEqual(pressed.call_count, 2)
        self.assertEqual(entry.cget("state"), "normal")
        self.assertEqual(disabled.cget("state"), "disabled")

    def test_child_configure_does_not_change_panel_drawing_dimensions(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        self.addCleanup(root.destroy)
        root.withdraw()
        panel = ctk.CTkFrame(root, width=301, height=375)
        child = tk.Frame(panel)
        grandchild = tk.Frame(child)
        activated = Mock()
        _bind_panel_activation(panel, activated)

        for target in (panel._canvas, child, grandchild):
            target.event_generate("<Configure>", width=140, height=25)
            self.assertEqual(panel._current_width, 301)
            self.assertEqual(panel._current_height, 375)
        activated.assert_not_called()
        for sequence in ("<ButtonPress>", "<KeyPress>", "<MouseWheel>", "<FocusIn>"):
            tag = grandchild.bindtags()[0]
            self.assertTrue(panel.bind_class(tag, sequence))
        root.deiconify()
        panel.pack()
        child.pack()
        grandchild.pack()
        root.update()
        activated.reset_mock()
        grandchild.event_generate("<ButtonPress-1>", x=0, y=0)
        activated.assert_called_once_with()
