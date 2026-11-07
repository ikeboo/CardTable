from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from cardtable.triggers._trigger import Trigger


@dataclass(frozen=True, slots=True)
class TriggerEvent:
    """One occurrence emitted by a trigger and delivered to its callbacks.

    ``event_id`` identifies an occurrence; ``trigger_id`` identifies its source
    for that source's lifetime. ``data`` carries trigger-specific values and
    should not be mutated after publication. Freezing the envelope does not
    freeze objects stored in ``data``, ``texts`` or ``images``. Named text and
    image fields default to empty dictionaries. JRPC images are numpy arrays;
    webhook images retain their filename/content metadata dictionaries.
    """

    trigger: "Trigger"
    timestamp: float
    data: Any = None
    event_id: str = field(default_factory=lambda: uuid4().hex)
    texts: dict[str, str] = field(default_factory=dict, kw_only=True)
    images: dict[str, Any] = field(default_factory=dict, kw_only=True)
    trigger_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "trigger_id", self.trigger.id)

    def response(
        self, texts: dict[str, str], images: dict[str, Any], image_format: str = "jpg"
    ) -> None:
        """Respond to this occurrence using its internal event identity.

        Images use JPEG by default; image_format="png" preserves alpha and pixels.
        The source must support responses. Expired or already answered requests
        raise RuntimeError; sources without responses raise NotImplementedError.
        """
        self.trigger._respond(self.event_id, texts, images, image_format=image_format)
