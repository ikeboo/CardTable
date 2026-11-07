"""Named texts and images received by or returned from a webhook callback."""

from typing import TypedDict


class WebhookImageData(TypedDict):
    """An uploaded image; its filename is metadata and is never used for storage."""

    filename: str
    content_type: str
    content: bytes


class WebhookEventData(TypedDict):
    """Named fields; callback results use the same shape with image bytes."""

    texts: dict[str, str]
    images: dict[str, WebhookImageData]
