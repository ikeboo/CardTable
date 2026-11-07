"""Image copy preserves source pixels and overlays an icon without a background."""

import sys
import tkinter as tk
import unittest
from unittest.mock import patch

import customtkinter as ctk
import numpy as np
from PIL import ImageGrab

from cardtable import Image


class ImageCopyTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        self.addCleanup(self.root.destroy)
        self.root.geometry("400x300")
        self.renderer = Image("Preview")._create_renderer(self.root)
        self.root.update()

    def render(self):
        self.root.after(50, self.root.quit)
        self.root.mainloop()

    def click_copy(self):
        canvas = self.renderer._label
        left, top, right, bottom = canvas.bbox(self.renderer._copy_button)
        x, y = (left + right) // 2, (top + bottom) // 2
        canvas.event_generate("<Motion>", x=x, y=y)
        self.root.update()
        canvas.event_generate("<Button-1>", x=x, y=y)
        self.root.update()

    def test_empty_image_shows_only_padding_before_and_after_an_image(self):
        canvas = self.renderer._label
        canvas.configure(background="#345678")
        for payload in (None, np.ones((10, 10, 3), dtype=np.uint8), None):
            self.renderer.update(payload)
            self.render()
            self.assertEqual(canvas.cget("background"), "#345678")
            if payload is None:
                self.assertIsNone(self.renderer._source_image)
                self.assertEqual(canvas.itemcget(self.renderer._image_item, "image"), "")
                self.assertEqual(
                    canvas.itemcget(self.renderer._copy_button, "state"), "hidden"
                )
                self.assertEqual(len(self.renderer._corner_images), 4)
            else:
                self.assertEqual(
                    canvas.itemcget(self.renderer._copy_button, "state"), "normal"
                )

    @unittest.skipUnless(sys.platform == "darwin", "macOS clipboard integration")
    def test_button_copies_current_full_resolution_pixels_and_alpha(self):
        canvas = self.renderer._label
        self.assertEqual(canvas.itemcget(self.renderer._copy_button, "state"), "hidden")
        for channels in (3, 4, 1):
            with self.subTest(channels=channels):
                pixels = np.zeros((480, 640, channels), dtype=np.uint8)
                pixels[:, :320] = [17, 83, 201, 127][:channels]
                pixels[:, 320:] = [211, 47, 5, 255][:channels]
                if channels == 1:
                    pixels = pixels[:, :, 0]
                    expected = np.repeat(pixels[:, :, None], 3, axis=2)
                else:
                    expected = pixels[:, :, [2, 1, 0, 3][:channels]]
                self.renderer.update(pixels)
                self.render()
                self.click_copy()
                copied = ImageGrab.grabclipboard()
                self.assertIsNotNone(copied)
                with copied:
                    self.assertEqual(copied.size, (640, 480))
                    mode = "RGBA" if channels == 4 else "RGB"
                    np.testing.assert_array_equal(
                        np.asarray(copied.convert(mode)), expected
                    )

    def test_icon_background_is_transparent_in_both_appearance_modes(self):
        previous = ctk.get_appearance_mode()
        self.addCleanup(ctk.set_appearance_mode, previous)
        for mode in ("Light", "Dark"):
            with self.subTest(mode=mode):
                ctk.set_appearance_mode(mode)
                self.renderer.update(np.full((480, 640, 3), 127, dtype=np.uint8))
                self.render()
                overlay = self.renderer._copy_image
                transparent = self.root.tk.call(
                    str(overlay), "transparency", "get", 0, 0
                )
                self.assertTrue(transparent)
                self.assertGreater(
                    self.renderer._label.find_all().index(self.renderer._copy_button),
                    self.renderer._label.find_all().index(self.renderer._image_item),
                )

    def test_button_stays_inside_top_right_of_image_when_resized(self):
        self.renderer.update(np.zeros((480, 640, 3), dtype=np.uint8))
        for width in (400, 260):
            self.root.geometry(f"{width}x300")
            self.render()
            canvas = self.renderer._label
            left, top, right, bottom = canvas.bbox(self.renderer._copy_button)
            self.assertLessEqual(right, canvas.winfo_width())
            self.assertGreater(left, canvas.winfo_width() / 2)
            self.assertGreaterEqual(top, 0)
            self.assertLessEqual(bottom, canvas.winfo_height())

    def test_copy_failure_is_reported_to_user(self):
        self.renderer.update(np.zeros((10, 10, 3), dtype=np.uint8))
        self.render()
        with (
            patch(
                "cardtable.widgets.elements.image.copy_image",
                side_effect=OSError("Clipboard unavailable"),
            ),
            patch(
                "cardtable.widgets.elements.image.messagebox.showerror"
            ) as showerror,
        ):
            self.click_copy()
        self.assertIn("Clipboard unavailable", showerror.call_args.args)

    def test_rounded_corners_are_reused_and_include_letterbox_padding(self):
        pixels = np.full((120, 640, 4), (17, 83, 201, 127), dtype=np.uint8)
        self.renderer.update(pixels)
        self.render()
        corners = tuple(self.renderer._corner_images)
        canvas = self.renderer._label
        right, bottom = canvas.winfo_width(), canvas.winfo_height()
        image_top = canvas.bbox(self.renderer._image_item)[1]
        self.assertGreater(image_top, 0)
        self.assertEqual(canvas.cget("background"), "black")
        radius = corners[0].width()
        expected = (
            (0, 0),
            (right - radius, 0),
            (0, bottom - radius),
            (right - radius, bottom - radius),
        )
        for item, position in zip(self.renderer._corner_items, expected):
            self.assertEqual(tuple(canvas.coords(item)), position)
        self.assertFalse(
            self.root.tk.call(str(corners[0]), "transparency", "get", 0, 0)
        )
        self.assertTrue(
            self.root.tk.call(
                str(corners[0]), "transparency", "get", radius - 1, radius - 1
            )
        )
        self.renderer.update(pixels)
        self.render()
        self.assertEqual(tuple(self.renderer._corner_images), corners)
        np.testing.assert_array_equal(
            np.asarray(self.renderer._source_image), pixels[:, :, [2, 1, 0, 3]]
        )

    def test_copy_button_geometry_stays_fixed_during_periodic_updates(self):
        self.renderer.update(np.zeros((480, 640, 3), dtype=np.uint8))
        self.render()
        canvas = self.renderer._label
        expected = canvas.bbox(self.renderer._copy_button)
        positions = []
        for index in range(10):
            self.root.after(
                index * 100,
                lambda value=index: self.renderer.update(
                    np.full((480, 640, 3), value, dtype=np.uint8)
                ),
            )
            self.root.after(
                index * 100 + 50,
                lambda: positions.append(canvas.bbox(self.renderer._copy_button)),
            )
        self.root.after(1100, self.root.quit)
        self.root.mainloop()
        self.assertEqual(positions, [expected] * 10)
