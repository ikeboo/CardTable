"""Card and element public API, loaded on first use."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ._layout import Row as Row
    from .card import Card
    from .card.popup_card import PopupCard
    from .deck import Deck
    from .elements import (
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
    from .elements.button import Btn, Button, ButtonControl
    from .elements.led import LED
    from .elements.result_button import CancelBtn, FalseBtn, TrueBtn
    from .elements.separator import Separator
    from .message_dialog import show_message

__all__ = [
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
    "CheckBox",
    "ComboBox",
    "Entry",
    "Element",
    "FileDialog",
    "FileDrop",
    "Image",
    "InputElement",
    "LED",
    "Number",
    "Gauge",
    "ProgressBar",
    "Radio",
    "Row",
    "RangeSlider",
    "SignalPlot",
    "Slider",
    "Switch",
    "Table",
    "Text",
    "Card",
]

_LAZY_IMPORTS = {
    "show_message": ("cardtable.widgets.message_dialog", "show_message"),
    "Table": ("cardtable.widgets.elements.table", "Table"),
    "SignalPlot": ("cardtable.widgets.elements.signal_plot", "SignalPlot"),
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
    "CheckBox": ("cardtable.widgets.elements", "CheckBox"),
    "ComboBox": ("cardtable.widgets.elements", "ComboBox"),
    "Entry": ("cardtable.widgets.elements", "Entry"),
    "FileDialog": ("cardtable.widgets.elements", "FileDialog"),
    "FileDrop": ("cardtable.widgets.elements", "FileDrop"),
    "Image": ("cardtable.widgets.elements", "Image"),
    "InputElement": ("cardtable.widgets.elements", "InputElement"),
    "LED": ("cardtable.widgets.elements", "LED"),
    "Number": ("cardtable.widgets.elements", "Number"),
    "Gauge": ("cardtable.widgets.elements.gauge", "Gauge"),
    "ProgressBar": ("cardtable.widgets.elements.progress_bar", "ProgressBar"),
    "Radio": ("cardtable.widgets.elements", "Radio"),
    "RangeSlider": ("cardtable.widgets.elements", "RangeSlider"),
    "Slider": ("cardtable.widgets.elements", "Slider"),
    "Switch": ("cardtable.widgets.elements", "Switch"),
    "Text": ("cardtable.widgets.elements", "Text"),
    "Card": ("cardtable.widgets.card.card", "Card"),
}


def __getattr__(name: str) -> Any:
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
