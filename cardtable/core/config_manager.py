"""Process-wide YAML configuration exposed through the cardtable API."""

from copy import deepcopy
from pathlib import Path
from threading import RLock

from ruamel.yaml import YAML

_lock = RLock()
_config_path: Path | None = None
_config: dict = {}


def _read_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        data = YAML(typ="safe").load(file)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("configuration must be a YAML mapping")
    return data


def _set_config_path(path: str | Path) -> None:
    """Load and remember a configuration file for subsequent reloads."""
    global _config_path, _config
    resolved = Path(path).resolve()
    with _lock:
        data = _read_config(resolved)
        _config_path = resolved
        _config = data


def get_config() -> dict:
    """Return an independent snapshot of the current configuration."""
    with _lock:
        return deepcopy(_config)


def reload_config() -> dict:
    """Reload the configured YAML file and return its contents."""
    global _config
    with _lock:
        if _config_path is None:
            raise RuntimeError("no configuration file has been specified")
        data = _read_config(_config_path)
        _config = data
        return deepcopy(_config)
