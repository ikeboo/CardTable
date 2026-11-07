"""Public payload types for filesystem notifications."""

from pathlib import Path
from typing import Literal, TypedDict

FileSystemEventKind = Literal["created", "modified", "deleted", "moved"]


class FileSystemEventData(TypedDict):
    """Absolute source path and optional destination for a filesystem change."""

    kind: FileSystemEventKind
    path: Path
    dest_path: Path | None
    is_directory: bool
