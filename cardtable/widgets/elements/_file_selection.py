"""Shared file selection validation and native dialog options."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ._input import InputElement

PathInput = str | os.PathLike[str]
Selection = str | tuple[str, ...] | None
SelectionInput = PathInput | tuple[PathInput, ...] | list[PathInput] | None


class _FileSelection(InputElement[Selection, SelectionInput]):
    extensions: str | tuple[str, ...] | list[str]
    directory: bool
    label: str | None
    multiple: bool

    def __post_init__(self) -> None:
        if not isinstance(self.directory, bool):
            raise TypeError("directory must be a bool")
        if not isinstance(self.multiple, bool):
            raise TypeError("multiple must be a bool")
        if self.directory and self.multiple:
            raise ValueError("multiple selection is only supported for files")
        if self.label is not None and not isinstance(self.label, str):
            raise TypeError("label must be a string or None")
        extensions = self.extensions
        if isinstance(extensions, str):
            extensions = (extensions,)
        if not isinstance(extensions, (tuple, list)):
            raise TypeError("extensions must be a string or a tuple/list of strings")
        normalized = []
        for extension in extensions:
            if not isinstance(extension, str):
                raise TypeError("extensions must contain strings")
            suffix = extension.removeprefix("*").removeprefix(".")
            if not suffix or any(char in suffix for char in "*?[]/\\ \t\r\n"):
                raise ValueError("extensions must be suffixes such as '.png'")
            normalized.append("." + suffix)
        self.extensions = tuple(normalized)

    @property
    def initial_value(self) -> tuple[str, ...] | None:
        return () if self.multiple else None

    def normalize(self, value: SelectionInput) -> Selection:
        if value is None:
            return self.initial_value
        if self.multiple:
            paths = value if isinstance(value, (tuple, list)) else (value,)
            return tuple(self._normalize_path(path) for path in paths)
        return self._normalize_path(value)

    def _normalize_path(self, value: PathInput) -> str:
        if not isinstance(value, (str, os.PathLike)):
            raise TypeError("value must be a path or None")
        if not os.fspath(value):
            raise ValueError("value must be a nonempty path or None")
        path = Path(value).expanduser().resolve()
        if self.directory:
            if not path.is_dir():
                raise ValueError("value must be an existing directory")
        else:
            if not path.is_file():
                raise ValueError("value must be an existing file")
            if self.extensions and not str(path).casefold().endswith(
                tuple(extension.casefold() for extension in self.extensions)
            ):
                raise ValueError("value must match one of the configured extensions")
        return str(path)


def _choose_path(element: _FileSelection, parent: Any, value: Selection) -> Any:
    from tkinter import filedialog

    options: dict[str, Any] = {"parent": parent.winfo_toplevel()}
    if value:
        first = value[0] if element.multiple else value
        path = Path(first)
        options["initialdir"] = str(path if element.directory else path.parent)
    if element.directory:
        selected = filedialog.askdirectory(mustexist=True, **options)
    else:
        if element.extensions:
            options["filetypes"] = [
                (
                    "Allowed files",
                    tuple("*" + ext for ext in element.extensions),
                )
            ]
        selected = (
            filedialog.askopenfilenames(**options)
            if element.multiple
            else filedialog.askopenfilename(**options)
        )
    return selected
