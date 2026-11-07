from threading import Thread
from typing import Optional

from pynput import keyboard

from cardtable.core.trigger_callback import TriggerCallback
from cardtable.data_classes.trigger_message import TriggerMessage

from ._trigger import Trigger


class KeyTrigger(Trigger):
    """Trigger for keyboard events

    Args:
        hotkey (str): The hotkey to trigger the event, e.g. "<ctrl>+k"
        callback: Callback dispatched by the Dealer when the hotkey is pressed.
        global_: Listen even when the application window is not active.
    """

    def __init__(
        self,
        hotkey: str,
        callback: TriggerCallback | None = None,
        *,
        global_: bool = False,
        drop_if_busy: bool = True,
        q_size: int = 10,
        log_level: str | int = "INFO",
    ):
        if not isinstance(global_, bool):
            raise TypeError("global_ must be a bool")
        super().__init__(
            callback=callback,
            drop_if_busy=drop_if_busy,
            q_size=q_size,
            log_level=log_level,
        )
        self.hotkey = hotkey
        self.global_ = global_
        self._listener: Optional[keyboard.GlobalHotKeys] = None
        self._watch_thread: Optional[Thread] = None

    def start(self):
        """Start listening for the configured hotkey."""
        if self.is_stopped:
            self._stop_event.clear()
            self.is_stopped = False

        if self._listener is not None and self._listener.running:
            return

        self._listener = keyboard.GlobalHotKeys({self.hotkey: self._on_activate})
        self._listener.start()

        self._watch_thread = Thread(target=self.watching_loop, daemon=True)
        self._watch_thread.start()

    def watching_loop(self):
        """Keep the trigger alive until stopped."""
        while not self._stop_event.is_set():
            if self._listener is None or not self._listener.running:
                break
            self._stop_event.wait(0.1)

        if self._listener is not None and self._listener.running:
            self._listener.stop()

    def stop(self):
        """Stop listening and release resources."""
        self._stop_event.set()
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass

        if self._watch_thread is not None and self._watch_thread.is_alive():
            self._watch_thread.join(timeout=1.0)

        self.is_stopped = True

    def _on_activate(self):
        if not self.global_:
            from cardtable.widgets._runtime import CardRuntime

            if not CardRuntime.instance().is_active():
                return
        message = TriggerMessage(
            timestamp=self.get_timestamp(),
            data={"hotkey": self.hotkey},
        )
        self._set_event(message)
