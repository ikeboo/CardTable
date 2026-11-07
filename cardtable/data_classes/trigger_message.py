from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class TriggerMessage:
    """Queued occurrence; identity and payload survive Dealer dispatch."""

    timestamp: float
    data: Any = None
    event_id: str = field(default_factory=lambda: uuid4().hex)
    texts: dict[str, str] = field(default_factory=dict, kw_only=True)
    images: dict[str, Any] = field(default_factory=dict, kw_only=True)
