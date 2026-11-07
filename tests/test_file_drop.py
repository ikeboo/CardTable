"""FileDrop selection restrictions and click/drop UI behavior."""

import pickle
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tkinterdnd2 import COPY, REFUSE_DROP

from cardtable import Card, FileDialog, FileDrop
from cardtable.core.closure import Closure
from cardtable.widgets.elements.file_drop import _file_drop_text


class FileDropTest(unittest.TestCase):
    def setUp(self):
        font = patch(
            "cardtable.widgets.elements._fonts.ctk_font", return_value=("Arial", 12)
        )
        font.start()
        self.addCleanup(font.stop)

    def tearDown(self):
        Closure().close_all()

    def build(self, element, emit):
        controls = []

        def control(*args, **kwargs):
            widget = Mock()
            widget.winfo_width.return_value = 300
            widget._font.measure.side_effect = len
            controls.append(widget)
            return widget

        with (
            patch("customtkinter.CTkFrame", side_effect=control),
            patch("customtkinter.CTkLabel", side_effect=control),
            patch("customtkinter.CTkFont"),
            patch("tkinterdnd2.TkinterDnD._require"),
        ):
            element.build_ui(Mock(), emit)
        targets = controls[2:5]  # area, icon, filename
        callbacks = []
        for target in targets:
            callbacks.append(target.dnd_bind.call_args.args[1])
            self.assertIn("<Button-1>", [c.args[0] for c in target.bind.call_args_list])
        label = element._ui._file_drop_label

        def drop(*paths):
            label.tk.splitlist.return_value = paths
            return callbacks[0](Mock(data="paths"))

        return element._ui, targets, drop

    def test_configuration_and_values_match_file_dialog(self):
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
                    FileDrop(**options)
        with tempfile.TemporaryDirectory() as directory:
            directory = str(Path(directory).resolve())
            path = Path(directory, "first.PNG")
            path.touch()
            for options in (
                {"extensions": ["png", "*.jpg"]},
                {"multiple": True, "extensions": "png"},
                {"directory": True, "extensions": "png"},
            ):
                drop, dialog = FileDrop(**options), FileDialog(**options)
                self.assertEqual(drop.extensions, dialog.extensions)
                self.assertEqual(drop.get(), dialog.get())
                value = directory if options.get("directory") else path
                drop.set(value)
                self.assertEqual(drop.get(), dialog.normalize(value))
                drop.reset()
                self.assertEqual(drop.get(), dialog.initial_value)
            self.assertEqual(FileDrop("Prompt", "Heading").label, "Heading")

    def test_clicks_on_area_icon_and_text_open_filtered_dialog(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = str(Path(directory).resolve())
            path = Path(directory, "image.png")
            path.touch()
            emitted = Mock()
            ui, targets, _ = self.build(FileDrop(extensions="png"), emitted)
            with patch(
                "tkinter.filedialog.askopenfilename", return_value=str(path)
            ) as ask:
                for target in targets:
                    click = next(
                        c.args[1]
                        for c in target.bind.call_args_list
                        if c.args[0] == "<Button-1>"
                    )
                    click(Mock())
                self.assertEqual(ask.call_count, 3)
                self.assertEqual(
                    ask.call_args.kwargs["filetypes"], [("Allowed files", ("*.png",))]
                )
                self.assertEqual(ask.call_args.kwargs["initialdir"], directory)
            with patch("tkinter.filedialog.askopenfilename", return_value=""):
                ui._choose()
            self.assertEqual(emitted.call_count, 3)
            ui.update_state("disabled", None)
            with patch("tkinter.filedialog.askopenfilename") as ask:
                ui._choose()
                ask.assert_not_called()
            self.assertEqual(ui._file_drop_value, str(path))

    def test_invalid_drops_preserve_value_and_show_error_below_area(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = str(Path(directory).resolve())
            valid = Path(directory, "image.PNG")
            invalid = Path(directory, "text.txt")
            valid.touch()
            invalid.touch()
            emitted = Mock()
            ui, _, drop = self.build(FileDrop(extensions="png"), emitted)
            self.assertEqual(drop(str(valid)), COPY)
            for paths in (
                (str(invalid),),
                (directory,),
                (str(valid) + ".missing",),
                (str(valid), str(valid)),
                (),
            ):
                with self.subTest(paths=paths):
                    self.assertEqual(drop(*paths), REFUSE_DROP)
                    self.assertEqual(ui._file_drop_value, str(valid))
                    self.assertTrue(ui._error.configure.call_args.kwargs["text"])
                    ui._error.pack.assert_called_with(fill="x", pady=(4, 0))
            emitted.assert_called_once_with(str(valid))
            ui._error.pack_forget.reset_mock()
            self.assertEqual(drop(str(valid)), COPY)
            ui._error.pack_forget.assert_called_once()
            ui.update_state("disabled", None)
            self.assertEqual(drop(str(valid)), REFUSE_DROP)
            self.assertEqual(emitted.call_count, 2)
            ui._error.pack_forget.reset_mock()
            ui.update(None)
            ui._error.pack_forget.assert_called_once()

    def test_multiple_files_cross_controller_boundary_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = str(Path(directory).resolve())
            paths = tuple(
                str(Path(directory, name)) for name in ("first.png", "second.png")
            )
            for path in paths:
                Path(path).touch()
            with Card(0, 0, 4, 3, "Files", runtime=Mock()) as card:
                element = FileDrop(multiple=True, extensions="png")
            ui_element = pickle.loads(pickle.dumps(element))
            emitted = Mock(
                side_effect=lambda value: card._receive_input({element.name: value})
            )
            ui, _, drop = self.build(ui_element, emitted)
            self.assertEqual(drop(*paths), COPY)
            self.assertEqual(element.get(), paths)
            self.assertEqual(
                _file_drop_text(ui_element, paths), "first.png; second.png"
            )
            self.assertEqual(drop(paths[0], directory), REFUSE_DROP)
            self.assertEqual(element.get(), paths)
            with patch("tkinter.filedialog.askopenfilenames", return_value=paths):
                ui._choose()
            self.assertEqual(emitted.call_count, 2)
            ui.update(())
            self.assertEqual(
                _file_drop_text(ui_element, ui._file_drop_value), ui_element.text
            )
            self.assertFalse(hasattr(pickle.loads(pickle.dumps(ui_element)), "_ui"))

    def test_directory_click_and_drop_ignore_extensions(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = str(Path(directory).resolve())
            path = Path(directory, "file.png")
            path.touch()
            emitted = Mock()
            ui, _, drop = self.build(
                FileDrop(directory=True, extensions="txt"), emitted
            )
            with patch(
                "tkinter.filedialog.askdirectory", return_value=directory
            ) as ask:
                ui._choose()
                self.assertTrue(ask.call_args.kwargs["mustexist"])
            self.assertEqual(drop(directory), COPY)
            self.assertEqual(drop(str(path)), REFUSE_DROP)
            self.assertEqual(emitted.call_count, 2)
