"""Overlay a scrollbar without changing the content's available space."""

from typing import Any


def update_scrollbar(
    scrollbar: Any, first: str, last: str, *, target: Any
) -> None:
    interval = (float(first), float(last))
    pending = getattr(scrollbar, "_cardtable_scroll_after_id", None)
    if pending is not None:
        scrollbar.after_cancel(pending)
        scrollbar._cardtable_scroll_after_id = None
    if getattr(scrollbar, "_cardtable_scroll_interval", None) == interval:
        return

    def apply() -> None:
        scrollbar._cardtable_scroll_after_id = None
        # CTkScrollbar.set synchronously processes idle drawing. Record this
        # before calling it so identical reentrant notifications are ignored.
        scrollbar._cardtable_scroll_interval = interval
        if float(first) <= 0 and float(last) >= 1:
            scrollbar.place_forget()
        elif not scrollbar.winfo_manager():
            scrollbar.place(
                in_=target, relx=1, relheight=1, anchor="ne", bordermode="outside"
            )
            scrollbar.lift()
        scrollbar.set(first, last)

    # CTkScrollbar.set() calls update_idletasks(). Calling it from Tk's
    # yscrollcommand re-enters drawing/placement on Aqua and can crash Tk.
    # A timer (not after_idle) lets the current redraw finish first.
    scrollbar._cardtable_scroll_after_id = scrollbar.after(0, apply)
