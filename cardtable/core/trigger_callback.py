"""Shared callback contract for triggers and buttons."""

from collections.abc import Callable
from functools import partial
from inspect import Parameter, iscoroutinefunction, signature
from typing import Any, get_type_hints

from cardtable.data_classes.trigger_event import TriggerEvent

TriggerCallback = Callable[[TriggerEvent], Any] | Callable[[], Any]


def validate_trigger_callback(callback: TriggerCallback | None) -> None:
    """Accept synchronous callbacks with no arguments or one annotated event."""
    if callback is None:
        return
    if not callable(callback):
        raise TypeError("trigger callback must be callable or None")

    name = getattr(callback, "__qualname__", type(callback).__qualname__)
    error = (
        f"trigger callback {name} must accept no arguments or one positional "
        "argument annotated as event: TriggerEvent"
    )
    try:
        parameters = tuple(signature(callback).parameters.values())
    except (TypeError, ValueError) as cause:
        raise TypeError(error) from cause
    if len(parameters) > 1 or (parameters and parameters[0].kind not in (
        Parameter.POSITIONAL_ONLY,
        Parameter.POSITIONAL_OR_KEYWORD,
    )):
        raise TypeError(error)

    target = callback
    while isinstance(target, partial):
        target = target.func
    if not hasattr(target, "__annotations__"):
        target = target.__call__
    if iscoroutinefunction(target):
        raise TypeError("trigger callback must be synchronous")
    if not parameters:
        return
    try:
        annotation = get_type_hints(target).get(parameters[0].name)
    except (NameError, TypeError, ValueError) as cause:
        raise TypeError(error) from cause
    if annotation is not TriggerEvent:
        raise TypeError(error)
