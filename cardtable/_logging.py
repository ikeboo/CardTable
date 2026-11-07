"""Convenient file logging configuration for CardTable applications."""

import logging
import re
import sys
from copy import copy
from datetime import datetime, timedelta
from os import PathLike
from pathlib import Path
from threading import RLock
from typing import Literal

logger = logging.getLogger("cardtable")
_lock = RLock()
_handler: "_CalendarFileHandler | None" = None
_rotations = {"daily", "hourly", "weekly"}


def _caller_name(frame) -> str:
    code = frame.f_code
    if hasattr(code, "co_qualname"):
        return code.co_qualname.rsplit(".<locals>.", 1)[-1]
    # Python 3.10 code objects do not retain the enclosing class name.
    scope = frame
    while scope is not None:
        candidates = list(scope.f_locals.values())
        if scope is frame:
            owner = frame.f_locals.get("self")
            if owner is not None:
                candidates.insert(0, type(owner))
        for candidate in candidates:
            if not isinstance(candidate, type):
                continue
            for cls in candidate.__mro__:
                method = vars(cls).get(code.co_name)
                if isinstance(method, (staticmethod, classmethod)):
                    method = method.__func__
                if getattr(method, "__code__", None) is code:
                    return f"{cls.__name__}.{code.co_name}"
        scope = scope.f_back
    return code.co_name


class _CallerFilter(logging.Filter):
    """Capture the caller before a record can cross a process boundary."""

    def filter(self, record: logging.LogRecord) -> bool:
        if hasattr(record, "cardtable_caller"):
            return True
        record.cardtable_caller = f"{record.module}.{record.funcName}"
        frame = sys._getframe()
        while frame is not None:
            code = frame.f_code
            if (
                code.co_filename == record.pathname
                and code.co_name == record.funcName
                and frame.f_lineno == record.lineno
            ):
                name = _caller_name(frame)
                if "." in name:
                    record.cardtable_caller = ".".join(name.split(".")[-2:])
                break
            frame = frame.f_back
        return True


class _LogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record = copy(record)
        suffix = f"_PID:{record.process}"
        name_width = max(0, 20 - len(suffix))
        name = {"MainProcess": "Main", "cardtable-ui": "UI"}.get(
            record.processName, record.processName
        )
        if len(name) > name_width:
            if name_width >= 3:
                name = name[:name_width - 3] + "..."
            else:
                name = name[:name_width]
        record.processName = self._column(name + suffix, max(20, len(suffix)))
        record.levelname = self._column(record.levelname, 8)
        record.cardtable_caller = self._column(record.cardtable_caller, 40)
        return super().format(record)

    @staticmethod
    def _column(value: str, width: int) -> str:
        if len(value) > width:
            value = value[:width - 3] + "..."
        return f"{value:<{width}}"


def _normalize_level(level: str | int) -> int:
    if isinstance(level, str):
        value = logging.getLevelName(level.upper())
        if not isinstance(value, int):
            raise ValueError(f"unknown log level: {level!r}") from None
        level = value
    if isinstance(level, bool) or not isinstance(level, int):
        raise TypeError("level must be a log level name or integer")
    return level


class _CalendarFileHandler(logging.FileHandler):
    """Write directly to the file named for the current calendar period."""

    def __init__(self, directory: Path, rotation: str, backup_count: int):
        self.directory = directory.resolve()
        self.rotation = rotation
        self.backup_count = backup_count
        self.period = self._period(datetime.now())
        super().__init__(self._path(self.period), encoding="utf-8")

    def _period(self, now: datetime) -> str:
        if self.rotation == "weekly":
            now -= timedelta(days=now.weekday())
        return now.strftime("%Y%m%d%H" if self.rotation == "hourly" else "%Y%m%d")

    def _path(self, period: str) -> Path:
        return self.directory / f"cardtable_{period}.log"

    def emit(self, record: logging.LogRecord) -> None:
        try:
            period = self._period(datetime.now())
            if period != self.period:
                if self.stream:
                    self.stream.close()
                    self.stream = None
                self.period = period
                self.baseFilename = str(self._path(period))
                self.stream = self._open()
                self._remove_old_files()
            super().emit(record)
        except Exception:
            self.handleError(record)

    def _remove_old_files(self) -> None:
        if not self.backup_count:
            return
        digits = 10 if self.rotation == "hourly" else 8
        pattern = re.compile(rf"cardtable_\d{{{digits}}}\.log\Z")
        files = sorted(
            path
            for path in self.directory.iterdir()
            if path.is_file()
            and pattern.fullmatch(path.name)
            and path.name != self._path(self.period).name
        )
        for path in files[:-self.backup_count]:
            path.unlink()


def set_logger(
    directory: str | PathLike[str],
    *,
    rotation: Literal["daily", "hourly", "weekly"] = "daily",
    level: str | int = "INFO",
    backup_count: int = 30,
) -> None:
    """Write CardTable logs to a rotating file in *directory*.

    Daily rotation occurs at local midnight; weekly rotation occurs on Monday.
    Existing file logging configured by this function is replaced.
    """
    if rotation not in _rotations:
        raise ValueError("rotation must be 'daily', 'hourly', or 'weekly'")
    level = _normalize_level(level)
    if isinstance(backup_count, bool) or not isinstance(backup_count, int):
        raise TypeError("backup_count must be an integer")
    if backup_count < 0:
        raise ValueError("backup_count must not be negative")

    global _handler
    with _lock:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        handler = _CalendarFileHandler(path, rotation, backup_count)
        handler.setLevel(level)
        handler.addFilter(_CallerFilter())
        handler.setFormatter(_LogFormatter(
            "%(asctime)s | %(levelname)s | %(processName)s | "
            "%(cardtable_caller)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        previous = _handler
        logger.setLevel(level)
        logger.addHandler(handler)
        _handler = handler
        if previous is not None:
            logger.removeHandler(previous)
            previous.close()
        logger.info("started%s", "-" * 50)
