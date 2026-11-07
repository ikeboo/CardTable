from threading import Event

from cardtable.data_classes.trigger_message import TriggerMessage


class MessageEvent(Event):
    """Custom event class for message passing"""

    def __init__(self):
        super().__init__()
        self.message = None

    def set_message(self, message: TriggerMessage):
        self.message = message
        self.set()

    def get_message(self):
        return self.message
