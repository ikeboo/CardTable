import unittest
from unittest.mock import Mock, patch

from PIL import Image

from cardtable.widgets._window_icon import _ICON_PATH, apply_window_icon


class WindowIconTest(unittest.TestCase):
    def test_bundled_icon_is_readable(self):
        with Image.open(_ICON_PATH) as image:
            self.assertEqual(image.format, "ICO")
            image.load()

    def test_windows_icon_survives_customtkinter_delayed_override(self):
        for default in (True, False):
            with self.subTest(default=default):
                window = Mock()
                with patch("cardtable.widgets._window_icon.sys.platform", "win32"):
                    apply_window_icon(window, default=default)
                window.wm_iconbitmap.assert_called_once_with(
                    bitmap=str(_ICON_PATH),
                    default=str(_ICON_PATH) if default else None,
                )
                delay, restore = window.after.call_args.args
                self.assertEqual(delay, 200)
                window.wm_iconbitmap.reset_mock()
                restore()
                window.wm_iconbitmap.assert_called_once()

    def test_photo_icon_uses_window_interpreter_and_keeps_image_alive(self):
        for default in (True, False):
            with (
                self.subTest(default=default),
                patch("cardtable.widgets._window_icon.sys.platform", "darwin"),
                patch("PIL.ImageTk.PhotoImage") as photo,
            ):
                window = Mock()
                apply_window_icon(window, default=default)
                self.assertIs(photo.call_args.kwargs["master"], window)
                window.iconphoto.assert_called_once_with(default, photo.return_value)
                self.assertIs(window._cardtable_icon_image, photo.return_value)


if __name__ == "__main__":
    unittest.main()
