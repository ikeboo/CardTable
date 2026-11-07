"""Native ComboBox creation, menu rebuild, and selection on bundled Tcl/Tk."""

import subprocess
import sys
import textwrap
import unittest


class ComboBoxTest(unittest.TestCase):
    def test_native_dropdown_rebuild_and_selection(self):
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent("""
                import customtkinter as ctk
                import cardtable as c

                root = ctk.CTk()
                root.withdraw()
                try:
                    events = []
                    combo = c.ComboBox(["a", "b"])
                    combo.build_ui(root, events.append)
                    widget = combo._ui._controls[0]
                    menu = widget._dropdown_menu
                    assert menu.index("end") == 1
                    menu.invoke(1)
                    assert combo._ui._variable.get() == "b"
                    assert events

                    menu.configure(values=[])
                    assert menu.index("end") is None
                    menu.configure(values=["a", "b"])
                    assert menu.index("end") == 1
                    menu.invoke(0)
                    assert combo._ui._variable.get() == "a"
                    root.update_idletasks()
                finally:
                    root.destroy()
            """)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
