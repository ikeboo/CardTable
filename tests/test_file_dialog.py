"""FileDialog value validation and native dialog interaction."""

import pickle
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cardtable import Card, Element, FileDialog
from cardtable.core.closure import Closure


class FileDialogTest(unittest.TestCase):
    def setUp(self):
        font = patch(
            "cardtable.widgets.elements._fonts.ctk_font", return_value=("Arial", 12)
        )
        font.start()
        self.addCleanup(font.stop)

    def tearDown(self):
        Closure().close_all()

    def build(self, element, emit):
        with (
            patch("customtkinter.CTkFrame"),
            patch("customtkinter.CTkLabel"),
            patch("customtkinter.CTkEntry"),
            patch("customtkinter.CTkButton") as button,
        ):
            element.build_ui(Mock(), emit)
        self.assertEqual(button.call_args.kwargs["text"], "...")
        self.assertEqual(button.call_args.kwargs["width"], 32)
        return button.call_args.kwargs["command"]

    def test_path_storage_filters_directory_and_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "image.PNG")
            path.touch()
            element = FileDialog(extensions=["png", "*.jpg"])
            self.assertIsInstance(element, Element)
            self.assertIsNone(element.get())
            element.set(path)
            self.assertEqual(element.value, str(path.resolve()))
            self.assertEqual(element.extensions, (".png", ".jpg"))
            for invalid in (directory, str(path) + ".missing", ""):
                with self.assertRaises(ValueError):
                    element.set(invalid)
            other = Path(directory, "other.txt")
            other.touch()
            with self.assertRaises(ValueError):
                element.set(other)
            element.reset()
            self.assertIsNone(element.value)
            folder = FileDialog(directory=True, extensions=".png")
            folder.set(Path(directory))
            self.assertEqual(folder.get(), str(Path(directory).resolve()))
            with self.assertRaises(ValueError):
                folder.set(path)

    def test_invalid_configuration(self):
        for options in (
            {"directory": 1},
            {"multiple": 1},
            {"directory": True, "multiple": True},
            {"label": 1},
            {"extensions": None},
            {"extensions": (1,)},
            {"extensions": ""},
            {"extensions": "*"},
            {"extensions": "a/b"},
        ):
            with self.subTest(options=options):
                with self.assertRaises((TypeError, ValueError)):
                    FileDialog(**options)

    def test_selection_cancel_and_updates_across_card_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "selected.png")
            path.touch()
            with Card(0, 0, 4, 3, "Path", runtime=Mock()) as card:
                element = FileDialog(".png", label="Source")
            ui_element = pickle.loads(pickle.dumps(element))
            emitted = Mock(
                side_effect=lambda value: card._receive_input({element.name: value})
            )
            choose = self.build(ui_element, emitted)
            with patch(
                "tkinter.filedialog.askopenfilename", return_value=str(path)
            ) as ask:
                choose()
                self.assertEqual(
                    ask.call_args.kwargs["filetypes"], [("Allowed files", ("*.png",))]
                )
                self.assertIn("parent", ask.call_args.kwargs)
            self.assertEqual(card.values(), (str(path.resolve()),))
            ui_element._ui._path.insert.assert_called_with(0, str(path))
            emitted.assert_called_once_with(str(path))
            with patch("tkinter.filedialog.askopenfilename", return_value="") as ask:
                choose()
                self.assertEqual(ask.call_args.kwargs["initialdir"], directory)
            self.assertEqual(ui_element._ui._selected_path, str(path))
            self.assertEqual(emitted.call_count, 1)
            ui_element.update_state_ui("disabled", None)
            with patch("tkinter.filedialog.askopenfilename") as ask:
                choose()
                ask.assert_not_called()
            ui_element.update_ui(None)
            ui_element._ui._path.configure.assert_called_with(state="disabled")
            ui_element.update_state_ui("normal", "Ready")
            ui_element._ui._path.configure.assert_called_with(state="readonly")
            ui_element.update_ui(str(path))
            self.assertEqual(emitted.call_count, 1)
            restored = pickle.loads(pickle.dumps(ui_element))
            self.assertFalse(hasattr(restored, "_ui"))

    def test_directory_dialog_and_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            element = FileDialog(directory=True)
            emitted = Mock()
            choose = self.build(element, emitted)
            with (
                patch("tkinter.filedialog.askdirectory", return_value=directory) as ask,
                patch("tkinter.filedialog.askopenfilename") as file_ask,
            ):
                choose()
                self.assertTrue(ask.call_args.kwargs["mustexist"])
                file_ask.assert_not_called()
            emitted.assert_called_once_with(directory)
            element.update_ui(None)
            self.assertIsNone(element._ui._selected_path)

    def test_multiple_selection_storage_display_cancel_and_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = (Path(directory, "first image.png"), Path(directory, "second.png"))
            for path in paths:
                path.touch()
            selected = tuple(str(path.resolve()) for path in paths)
            with Card(0, 0, 4, 3, "Files", runtime=Mock()) as card:
                element = FileDialog(".png", multiple=True)
            self.assertEqual(element.get(), ())
            ui_element = pickle.loads(pickle.dumps(element))
            emitted = Mock(
                side_effect=lambda value: card._receive_input({element.name: value})
            )
            choose = self.build(ui_element, emitted)
            with (
                patch("tkinter.filedialog.askopenfilenames", return_value=selected),
                patch("tkinter.filedialog.askopenfilename") as single,
            ):
                choose()
                single.assert_not_called()
            self.assertEqual(element.get(), selected)
            self.assertEqual(card.values(), (selected,))
            ui_element._ui._path.insert.assert_called_with(0, "; ".join(selected))
            emitted.assert_called_once_with(selected)
            with patch("tkinter.filedialog.askopenfilenames", return_value=()) as ask:
                choose()
                self.assertEqual(
                    ask.call_args.kwargs["initialdir"], str(paths[0].parent.resolve())
                )
            self.assertEqual(ui_element._ui._selected_path, selected)
            self.assertEqual(emitted.call_count, 1)
            element.set(list(paths))
            self.assertEqual(element.get(), selected)
            element.set(paths[0])
            self.assertEqual(element.get(), selected[:1])
            element.set(paths)
            with self.assertRaises(ValueError):
                element.set([paths[0], Path(directory, "missing.png")])
            self.assertEqual(element.get(), selected)
            for invalid in ([paths[0], None], [42]):
                with self.assertRaises(TypeError):
                    element.set(invalid)
            element.reset()
            self.assertEqual(element.get(), ())
            ui_element.update_ui(element.get())
            self.assertEqual(ui_element._ui._selected_path, ())
            self.assertEqual(emitted.call_count, 1)
            element.set(None)
            self.assertEqual(element.get(), ())

    def test_single_selection_rejects_sequences(self):
        for value in ([], (), ["file.png"]):
            with self.assertRaises(TypeError):
                FileDialog().set(value)


if __name__ == "__main__":
    unittest.main()
