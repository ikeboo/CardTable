"""Platform cursors matching CustomTkinter buttons."""

import sys

CLICK_CURSOR = (
    "pointinghand"
    if sys.platform == "darwin"
    else "hand2" if sys.platform.startswith("win") else ""
)
