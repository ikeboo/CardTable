"""Static constructor checks: run with Pyright without launching a UI."""

from typing_extensions import assert_type

import cardtable as c


def font_scale_types() -> None:
    c.Element(font_scale=1.5)
    c.InputElement(font_scale=1.5)
    c.Label("Label", font_scale=1.5)
    c.BoxedLabel("Badge", font_scale=1.5)
    c.Button("Run", font_scale=1.5)
    c.Btn("Run", font_scale=1.5)
    c.TrueBtn("Yes", font_scale=1.5)
    c.FalseBtn("No", font_scale=1.5)
    c.CancelBtn("Cancel", font_scale=1.5)
    c.Entry(font_scale=1.5)
    c.CheckBox(font_scale=1.5)
    c.Switch(font_scale=1.5)
    c.Radio(["A", "B"], font_scale=1.5)
    c.ComboBox(["A", "B"], font_scale=1.5)
    c.Slider(0, 100, 1, font_scale=1.5)
    c.RangeSlider(0, 100, 1, font_scale=1.5)
    c.Number(0, 100, 1, font_scale=1.5)
    c.FileDialog(font_scale=1.5)
    c.FileDrop(font_scale=1.5)
    c.Text(font_scale=1.5)
    c.Image(font_scale=1.5)
    c.Table(["Name"], 2, font_scale=1.5)
    c.SignalPlot(font_scale=1.5)
    c.ProgressBar(font_scale=1.5)
    c.Gauge(font_scale=1.5)
    c.LED("red", font_scale=1.5)
    c.Separator("Section", font_scale=1.5)
    assert_type(c.Label("Label").font_scale, float)
    assert_type(c.Entry().font_scale, float)
