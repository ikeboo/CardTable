"""Static API checks: run with Pyright, without launching a UI."""

from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from typing_extensions import assert_type

import cardtable as c
from cardtable.triggers._trigger import Trigger


def trigger_event_types(event: c.TriggerEvent) -> None:
    assert_type(event.trigger, Trigger)
    assert_type(event.event_id, str)
    assert_type(event.trigger_id, str)
    assert_type(event.timestamp, float)
    assert_type(event.data, Any)


def event_callback(event: c.TriggerEvent) -> None:
    pass


def callback_types() -> None:
    c.Button("Run", callback=event_callback)
    c.TimerTrigger(100, callback=event_callback)
    c.KeyTrigger("<ctrl>+k", callback=event_callback)
    c.FileSystemTrigger(".", callback=event_callback, events=("created", "moved"))
    c.ScheduleTrigger(
        ("0 9 * * *", "0 18 * * *"), callback=event_callback, timezone=None
    )
    c.WebhookTrigger(port=0, callback=event_callback)


def webhook_payload_types(event: c.TriggerEvent) -> None:
    data: c.WebhookEventData = event.data
    assert_type(data["texts"], dict[str, str])
    assert_type(data["images"], dict[str, c.WebhookImageData])
    assert_type(data["images"]["before"]["content"], bytes)
    assert_type(data["images"]["before"]["filename"], str)
    assert_type(data["images"]["before"]["content_type"], str)


def schedule_payload_types(event: c.TriggerEvent) -> None:
    data: c.ScheduleEventData = event.data
    assert_type(data["scheduled_at"], datetime)
    assert_type(data["schedules"], tuple[str, ...])


def filesystem_payload_types(event: c.TriggerEvent) -> None:
    data: c.FileSystemEventData = event.data
    assert_type(data["kind"], c.FileSystemEventKind)
    assert_type(data["path"], Path)
    assert_type(data["dest_path"], Path | None)
    assert_type(data["is_directory"], bool)


def popup_types() -> None:
    with c.PopupCard("Warning", duration_sec=3) as card:
        with c.Row():
            yes = c.TrueBtn("Yes")
            no = c.FalseBtn("No")
            cancel = c.CancelBtn("Cancel")
    assert_type(yes, c.TrueBtn)
    assert_type(no, c.FalseBtn)
    assert_type(cancel, c.CancelBtn)
    assert_type(card.wait(), bool | None)
    assert_type(card.close(), None)


class App(c.Dealer):
    def setup(self):
        with c.Card(0, 0, 4, 4, "Card") as self.card:
            self.mode = c.Radio(["A", "B"])
            self.value = c.Slider(0, 100, 1)
            self.entry = c.Entry("Input here")
            self.check = c.CheckBox()
            self.image = c.Image()
            self.text = c.Text()
            self.range = c.RangeSlider(0, 100, 1)
            self.file = c.FileDrop()
            self.file_dialog = c.FileDialog(extensions=".png")
            self.files_dialog = c.FileDialog(multiple=True)
            with c.Row():
                self.capture = c.Button("Capture")
                self.clear = c.Btn("Clear")
            with c.Row():
                self.mode2 = c.Radio(["A", "B"])
                self.value2 = c.Slider(0, 10, 1)

    def check_types(self):
        assert_type(self.mode.get(), str)
        assert_type(self.value.get(), float)
        assert_type(self.entry.get(), str)
        assert_type(self.check.get(), bool)
        assert_type(self.mode2, c.Radio)
        assert_type(self.value2, c.Slider)
        assert_type(self.image.get(), np.ndarray | None)
        assert_type(self.text.get(), str)
        assert_type(self.range.get(), tuple[float, float])
        assert_type(self.file.get(), str | None)
        assert_type(self.file_dialog, c.FileDialog)
        assert_type(self.files_dialog, c.FileDialog)
        assert_type(self.file_dialog.get(), str | tuple[str, ...] | None)
        assert_type(self.files_dialog.get(), str | tuple[str, ...] | None)
        assert_type(self.capture, c.Button)
        assert_type(self.clear, c.Button)
        assert_type(self.clear, c.Btn)
