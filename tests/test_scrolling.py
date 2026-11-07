"""Regression checks for automatic scrollbar visibility."""

import tkinter as tk
import unittest
from unittest.mock import Mock

import customtkinter as ctk

from cardtable.widgets._scrolling import update_scrollbar


class ScrollbarTest(unittest.TestCase):
    def setUp(self):
        self.scrollbar = Mock()
        self.scrollbar._cardtable_scroll_after_id = None
        self.pending = {}
        self.next_id = 0

        def after(delay, callback):
            self.assertEqual(delay, 0)
            self.next_id += 1
            self.pending[self.next_id] = callback
            return self.next_id

        self.scrollbar.after.side_effect = after
        self.scrollbar.after_cancel.side_effect = self.pending.pop
        self.target = Mock()

    def run_timer(self):
        token = next(iter(self.pending))
        self.pending.pop(token)()

    def test_scrollbar_update_waits_until_tk_redraw_returns(self):
        self.scrollbar.winfo_manager.return_value = ""
        update_scrollbar(self.scrollbar, "0", "0.5", target=self.target)
        self.scrollbar.place.assert_not_called()
        self.scrollbar.set.assert_not_called()
        self.run_timer()
        self.scrollbar.place.assert_called_once_with(
            in_=self.target, relx=1, relheight=1, anchor="ne", bordermode="outside"
        )
        self.scrollbar.set.assert_called_once_with("0", "0.5")
        self.assertIsNone(self.scrollbar._cardtable_scroll_after_id)

    def test_newer_notification_replaces_pending_update(self):
        update_scrollbar(self.scrollbar, "0", "0.5", target=self.target)
        update_scrollbar(self.scrollbar, "0", "1", target=self.target)
        self.assertEqual(len(self.pending), 1)
        self.run_timer()
        self.scrollbar.place.assert_not_called()
        self.scrollbar.place_forget.assert_called_once()

        self.scrollbar.set.assert_called_once_with("0", "1")

    def test_notification_during_set_waits_for_next_timer(self):
        def set_range(first, last):
            if last == "0.5":
                update_scrollbar(self.scrollbar, "0", "1", target=self.target)

        self.scrollbar.set.side_effect = set_range
        update_scrollbar(self.scrollbar, "0", "0.5", target=self.target)
        self.run_timer()
        self.scrollbar.set.assert_called_once_with("0", "0.5")
        self.run_timer()
        self.scrollbar.set.assert_called_with("0", "1")
        self.scrollbar.place_forget.assert_called_once()

    def test_identical_range_does_not_reenter_drawing(self):
        self.scrollbar.set.side_effect = lambda first, last: update_scrollbar(
            self.scrollbar, first, last, target=self.target
        )
        update_scrollbar(self.scrollbar, "0", "0.5", target=self.target)
        self.run_timer()
        self.assertFalse(self.pending)
        update_scrollbar(self.scrollbar, "0.0", "0.50", target=self.target)
        self.assertFalse(self.pending)
        self.scrollbar.set.assert_called_once()

    def test_return_to_applied_range_cancels_pending_range(self):
        update_scrollbar(self.scrollbar, "0", "0.5", target=self.target)
        self.run_timer()
        update_scrollbar(self.scrollbar, "0", "1", target=self.target)
        update_scrollbar(self.scrollbar, "0", "0.5", target=self.target)
        self.assertFalse(self.pending)
        self.assertIsNone(self.scrollbar._cardtable_scroll_after_id)
        self.scrollbar.set.assert_called_once_with("0", "0.5")


class NativeScrollbarTest(unittest.TestCase):
    def test_scroll_notification_does_not_process_pending_tk_drawing(self):
        try:
            root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        self.addCleanup(root.destroy)
        root.withdraw()
        canvas = tk.Canvas(root)
        scrollbar = ctk.CTkScrollbar(root)
        idle_calls = []
        root.after_idle(lambda: idle_calls.append(True))

        update_scrollbar(scrollbar, "0", "0.5", target=canvas)
        # CTkScrollbar.set() would synchronously run this pending idle callback
        # inside the scroll notification, re-entering Tk's drawing/placement.
        self.assertEqual(idle_calls, [])
        root.update()
        self.assertEqual(idle_calls, [True])
        self.assertEqual(scrollbar.get(), (0.0, 0.5))
