"""Public element API, loaded on first use."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ._input import InputElement as InputElement
    from ._input import InputEvent as InputEvent
    from .base import Element as Element
    from .boxed_label import BoxedLabel as BoxedLabel
    from .button import Btn as Btn
    from .button import Button as Button
    from .button import ButtonControl as ButtonControl
    from .check_box import CheckBox as CheckBox
    from .combo_box import ComboBox as ComboBox
    from .entry import Entry as Entry
    from .file_dialog import FileDialog as FileDialog
    from .file_drop import FileDrop as FileDrop
    from .gauge import Gauge as Gauge
    from .image import Image as Image
    from .label import Label as Label
    from .led import LED as LED
    from .number import Number as Number
    from .progress_bar import ProgressBar as ProgressBar
    from .radio import Radio as Radio
    from .range_slider import RangeSlider as RangeSlider
    from .result_button import CancelBtn as CancelBtn
    from .result_button import FalseBtn as FalseBtn
    from .result_button import TrueBtn as TrueBtn
    from .separator import Separator as Separator
    from .signal_plot import SignalPlot as SignalPlot
    from .slider import Slider as Slider
    from .switch import Switch as Switch
    from .table import Table as Table
    from .text import Text as Text

__all__ = [
    "Separator",
    "BoxedLabel",
    "Label",
    "Button",
    "Btn",
    "TrueBtn",
    "FalseBtn",
    "CancelBtn",
    "ButtonControl",
    "CheckBox",
    "ComboBox",
    "Element",
    "Entry",
    "FileDialog",
    "FileDrop",
    "Image",
    "InputElement",
    "InputEvent",
    "LED",
    "Number",
    "Gauge",
    "ProgressBar",
    "Radio",
    "RangeSlider",
    "SignalPlot",
    "Slider",
    "Switch",
    "Table",
    "Text",
]

_LAZY_IMPORTS = {
    "Table": ("cardtable.widgets.elements.table", "Table"),
    "SignalPlot": ("cardtable.widgets.elements.signal_plot", "SignalPlot"),
    "TrueBtn": ("cardtable.widgets.elements.result_button", "TrueBtn"),
    "FalseBtn": ("cardtable.widgets.elements.result_button", "FalseBtn"),
    "CancelBtn": ("cardtable.widgets.elements.result_button", "CancelBtn"),
    "Label": ("cardtable.widgets.elements.label", "Label"),
    "BoxedLabel": ("cardtable.widgets.elements.boxed_label", "BoxedLabel"),
    "Element": ("cardtable.widgets.elements.base", "Element"),
    "Button": ("cardtable.widgets.elements.button", "Button"),
    "Btn": ("cardtable.widgets.elements.button", "Btn"),
    "ButtonControl": ("cardtable.widgets.elements.button", "ButtonControl"),
    "Image": ("cardtable.widgets.elements.image", "Image"),
    "Separator": ("cardtable.widgets.elements.separator", "Separator"),
    "LED": ("cardtable.widgets.elements.led", "LED"),
    "Gauge": ("cardtable.widgets.elements.gauge", "Gauge"),
    "ProgressBar": ("cardtable.widgets.elements.progress_bar", "ProgressBar"),
    "Text": ("cardtable.widgets.elements.text", "Text"),
    "InputElement": ("cardtable.widgets.elements._input", "InputElement"),
    "InputEvent": ("cardtable.widgets.elements._input", "InputEvent"),
    "Radio": ("cardtable.widgets.elements.radio", "Radio"),
    "ComboBox": ("cardtable.widgets.elements.combo_box", "ComboBox"),
    "Slider": ("cardtable.widgets.elements.slider", "Slider"),
    "RangeSlider": ("cardtable.widgets.elements.range_slider", "RangeSlider"),
    "Number": ("cardtable.widgets.elements.number", "Number"),
    "Entry": ("cardtable.widgets.elements.entry", "Entry"),
    "FileDialog": ("cardtable.widgets.elements.file_dialog", "FileDialog"),
    "FileDrop": ("cardtable.widgets.elements.file_drop", "FileDrop"),
    "Switch": ("cardtable.widgets.elements.switch", "Switch"),
    "CheckBox": ("cardtable.widgets.elements.check_box", "CheckBox"),
}


def __getattr__(name: str) -> Any:
    try:
        module, attribute = _LAZY_IMPORTS[name]
    except KeyError as error:
        message = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(message) from error
    value = getattr(import_module(module), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted((*globals(), *__all__))
