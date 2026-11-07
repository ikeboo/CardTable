"""Shared copy icon and native image clipboard transport."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import customtkinter as ctk
from PIL import Image, ImageDraw

from .. import theme


def _copy_icon(*, compact: bool = False) -> ctk.CTkImage:
    images = []
    for color in (
        theme.COPY_ICON_COLOR
        if isinstance(theme.COPY_ICON_COLOR, (tuple, list))
        else (theme.COPY_ICON_COLOR, theme.COPY_ICON_COLOR)
    ):
        image = Image.new("RGBA", (48, 48))
        draw = ImageDraw.Draw(image)
        draw.line([(30, 12), (30, 6), (6, 6), (6, 30), (12, 30)], fill=color, width=3)
        draw.rounded_rectangle((16, 16, 42, 42), radius=3, outline=color, width=3)
        images.append(image.crop(image.getbbox()) if compact else image)
    size = (12, 12) if compact else (16, 16)
    return ctk.CTkImage(light_image=images[0], dark_image=images[1], size=size)


def copy_image(image: Image.Image) -> None:
    """Publish image pixels, rather than a file path, to the system clipboard."""
    if sys.platform in {"darwin", "win32"}:
        with TemporaryDirectory(prefix="cardtable-clipboard-") as directory:
            path = Path(directory) / "image.png"
            image.save(path, format="PNG")
            if sys.platform == "darwin":
                script = (
                    "on run argv\n"
                    "set the clipboard to (read (POSIX file (item 1 of argv)) "
                    "as «class PNGf»)\n"
                    "end run"
                )
                command = ["osascript", "-e", script, str(path)]
                options = {}
            else:
                script = (
                    "$ErrorActionPreference = 'Stop'; "
                    "Add-Type -AssemblyName System.Windows.Forms; "
                    "Add-Type -AssemblyName System.Drawing; "
                    "$image = [System.Drawing.Image]::FromFile("
                    "$env:CARDTABLE_CLIPBOARD_IMAGE); "
                    "try { [System.Windows.Forms.Clipboard]::SetImage($image) } "
                    "finally { $image.Dispose() }"
                )
                command = [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-STA",
                    "-Command",
                    script,
                ]
                options = {
                    "env": dict(os.environ, CARDTABLE_CLIPBOARD_IMAGE=str(path))
                }
            subprocess.run(
                command, check=True, capture_output=True, timeout=15, **options
            )
        return

    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        command = ["wl-copy", "--type", "image/png"]
    elif shutil.which("xclip"):
        command = ["xclip", "-selection", "clipboard", "-target", "image/png"]
    else:
        raise RuntimeError("Image copy requires wl-copy (Wayland) or xclip (X11).")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    subprocess.run(command, input=buffer.getvalue(), check=True, timeout=15)
