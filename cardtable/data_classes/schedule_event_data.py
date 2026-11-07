"""Public payload type for scheduled occurrences."""

from datetime import datetime
from typing import TypedDict


class ScheduleEventData(TypedDict):
    """Planned zoned time and the normalized cron expressions matching it."""

    scheduled_at: datetime
    schedules: tuple[str, ...]
