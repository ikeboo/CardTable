"""Apply the bundled icon to the application and its windows."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_ICON_PATH = Path(__file__).with_name("icon.ico")


def apply_window_icon(window: Any, *, default: bool = False) -> None:
    if sys.platform == "win32":
        def set_icon() -> None:
            window.wm_iconbitmap(
                bitmap=str(_ICON_PATH),
                default=str(_ICON_PATH) if default else None,
            )

        set_icon()
        # CTkToplevel unconditionally installs its own icon after 200 ms.
        # Register after its constructor so our icon is applied last.
        window.after(200, set_icon)
    else:
        from PIL import Image, ImageTk

        with Image.open(_ICON_PATH) as image:
            photo = ImageTk.PhotoImage(image, master=window)
        window.iconphoto(default, photo)
        # Tk does not keep the Python image alive.
        window._cardtable_icon_image = photo
