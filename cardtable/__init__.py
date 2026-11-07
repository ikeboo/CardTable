"""Public API for :mod:`cardtable`, loaded on first use."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ._logging import logger, set_logger
    from .core.config_manager import get_config, reload_config
    from .core.dealer import Dealer
    from .data_classes.file_system_event_data import (
        FileSystemEventData,
        FileSystemEventKind,
    )
    from .data_classes.schedule_event_data import ScheduleEventData
    from .data_classes.trigger_event import TriggerEvent
    from .data_classes.trigger_message import TriggerMessage
    from .data_classes.webhook_event_data import WebhookEventData, WebhookImageData
    from .services.camera import Camera
    from .services.web_image_acquirer import WebImageAcquirer
    from .triggers.file_system_trigger import FileSystemTrigger
    from .triggers.jrpc import JRPCTrigger
    from .triggers.keyboard_trigger import KeyTrigger
    from .triggers.schedule_trigger import ScheduleTrigger
    from .triggers.timer_trigger import TimerTrigger
    from .triggers.webhook import WebhookTrigger
    from .widgets._layout import Row as Row
    from .widgets.card import Card
    from .widgets.card.popup_card import PopupCard
    from .widgets.deck import Deck
    from .widgets.elements import (
        BoxedLabel,
        CheckBox,
        ComboBox,
        Element,
        Entry,
        FileDialog,
        FileDrop,
        Gauge,
        Image,
        InputElement,
        InputEvent,
        Label,
        Number,
        ProgressBar,
        Radio,
        RangeSlider,
        SignalPlot,
        Slider,
        Switch,
        Table,
        Text,
    )
    from .widgets.elements.button import Btn, Button, ButtonControl
    from .widgets.elements.led import LED
    from .widgets.elements.result_button import CancelBtn, FalseBtn, TrueBtn
    from .widgets.elements.separator import Separator
    from .widgets.message_dialog import show_message

__all__ = [
    "logger",
    "set_logger",
    "get_config",
    "reload_config",
    "Deck",
    "PopupCard",
    "show_message",
    "TrueBtn",
    "FalseBtn",
    "CancelBtn",
    "Separator",
    "BoxedLabel",
    "Label",
    "Button",
    "Btn",
    "ButtonControl",
    "Camera",
    "CheckBox",
    "ComboBox",
    "Entry",
    "Element",
    "FileDialog",
    "FileDrop",
    "FileSystemTrigger",
    "FileSystemEventData",
    "FileSystemEventKind",
    "Dealer",
    "Image",
    "InputElement",
    "InputEvent",
    "LED",
    "Number",
    "Gauge",
    "ProgressBar",
    "JRPCTrigger",
    "KeyTrigger",
    "Radio",
    "Row",
    "RangeSlider",
    "SignalPlot",
    "Slider",
    "Switch",
    "Table",
    "Text",
    "Card",
    "TimerTrigger",
    "ScheduleTrigger",
    "ScheduleEventData",
    "WebhookTrigger",
    "WebhookEventData",
    "WebhookImageData",
    "TriggerMessage",
    "TriggerEvent",
    "WebImageAcquirer",
]

_LAZY_IMPORTS = {
    "logger": ("cardtable._logging", "logger"),
    "set_logger": ("cardtable._logging", "set_logger"),
    "get_config": ("cardtable.core.config_manager", "get_config"),
    "reload_config": ("cardtable.core.config_manager", "reload_config"),
    "show_message": ("cardtable.widgets.message_dialog", "show_message"),
    "Table": ("cardtable.widgets.elements.table", "Table"),
    "SignalPlot": ("cardtable.widgets.elements.signal_plot", "SignalPlot"),
    "JRPCTrigger": ("cardtable.triggers.jrpc", "JRPCTrigger"),
    "WebhookTrigger": ("cardtable.triggers.webhook", "WebhookTrigger"),
    "WebhookEventData": (
        "cardtable.data_classes.webhook_event_data", "WebhookEventData"
    ),
    "WebhookImageData": (
        "cardtable.data_classes.webhook_event_data", "WebhookImageData"
    ),
    "ScheduleTrigger": ("cardtable.triggers.schedule_trigger", "ScheduleTrigger"),
    "ScheduleEventData": (
        "cardtable.data_classes.schedule_event_data", "ScheduleEventData"
    ),
    "FileSystemTrigger": (
        "cardtable.triggers.file_system_trigger", "FileSystemTrigger"
    ),
    "FileSystemEventData": (
        "cardtable.data_classes.file_system_event_data", "FileSystemEventData"
    ),
    "FileSystemEventKind": (
        "cardtable.data_classes.file_system_event_data", "FileSystemEventKind"
    ),
    "PopupCard": ("cardtable.widgets.card.popup_card", "PopupCard"),
    "TrueBtn": ("cardtable.widgets.elements.result_button", "TrueBtn"),
    "FalseBtn": ("cardtable.widgets.elements.result_button", "FalseBtn"),
    "CancelBtn": ("cardtable.widgets.elements.result_button", "CancelBtn"),
    "Deck": ("cardtable.widgets.deck", "Deck"),
    "Label": ("cardtable.widgets.elements.label", "Label"),
    "BoxedLabel": ("cardtable.widgets.elements.boxed_label", "BoxedLabel"),
    "Row": ("cardtable.widgets._layout", "Row"),
    "Element": ("cardtable.widgets.elements", "Element"),
    "Separator": ("cardtable.widgets.elements", "Separator"),
    "Button": ("cardtable.widgets.elements.button", "Button"),
    "Btn": ("cardtable.widgets.elements.button", "Btn"),
    "ButtonControl": ("cardtable.widgets.elements.button", "ButtonControl"),
    "Camera": ("cardtable.services.camera", "Camera"),
    "CheckBox": ("cardtable.widgets.elements", "CheckBox"),
    "ComboBox": ("cardtable.widgets.elements", "ComboBox"),
    "Entry": ("cardtable.widgets.elements", "Entry"),
    "FileDialog": ("cardtable.widgets.elements", "FileDialog"),
    "FileDrop": ("cardtable.widgets.elements", "FileDrop"),
    "Dealer": ("cardtable.core.dealer", "Dealer"),
    "Image": ("cardtable.widgets.elements", "Image"),
    "InputElement": ("cardtable.widgets.elements", "InputElement"),
    "InputEvent": ("cardtable.widgets.elements", "InputEvent"),
    "LED": ("cardtable.widgets.elements", "LED"),
    "Number": ("cardtable.widgets.elements", "Number"),
    "Gauge": ("cardtable.widgets.elements.gauge", "Gauge"),
    "ProgressBar": ("cardtable.widgets.elements.progress_bar", "ProgressBar"),
    "KeyTrigger": ("cardtable.triggers.keyboard_trigger", "KeyTrigger"),
    "Radio": ("cardtable.widgets.elements", "Radio"),
    "RangeSlider": ("cardtable.widgets.elements", "RangeSlider"),
    "Slider": ("cardtable.widgets.elements", "Slider"),
    "Switch": ("cardtable.widgets.elements", "Switch"),
    "Text": ("cardtable.widgets.elements", "Text"),
    "Card": ("cardtable.widgets.card.card", "Card"),
    "TimerTrigger": ("cardtable.triggers.timer_trigger", "TimerTrigger"),
    "TriggerMessage": (
        "cardtable.data_classes.trigger_message",
        "TriggerMessage",
    ),
    "TriggerEvent": (
        "cardtable.data_classes.trigger_event",
        "TriggerEvent",
    ),
    "WebImageAcquirer": (
        "cardtable.services.web_image_acquirer",
        "WebImageAcquirer",
    ),
}


def __getattr__(name: str) -> Any:
    """Import and cache a public attribute when it is first requested."""
    try:
        module_name, attribute_name = _LAZY_IMPORTS[name]
    except KeyError as error:
        message = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(message) from error

    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted((*globals(), *__all__))
