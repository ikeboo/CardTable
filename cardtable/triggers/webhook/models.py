"""Pydantic models shared by validation, serialization and OpenAPI."""

from __future__ import annotations

import base64
import binascii
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from cardtable.data_classes.webhook_event_data import WebhookEventData


def _unicode(value: str) -> str:
    value.encode("utf-8")
    return value


Text = Annotated[str, AfterValidator(_unicode)]
Name = Annotated[Text, Field(min_length=1)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ImageMetadata(StrictModel):
    filename: Name = Field(description="Metadata only; never used as a storage path")
    content_type: str = Field(pattern=r"(?i)^image/[a-z0-9!#$&^_.+-]+$")

    @field_validator("content_type")
    @classmethod
    def lowercase(cls, value: str) -> str:
        return value.lower()


class WireImage(ImageMetadata):
    content_base64: str = Field(
        min_length=4,
        description="Nonempty image bytes as plain Base64 (no data URL or whitespace)",
        json_schema_extra={"contentEncoding": "base64"},
    )

    @field_validator("content_base64")
    @classmethod
    def valid_base64(cls, value: str) -> str:
        try:
            decoded = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError("Invalid Base64 image") from error
        if not decoded:
            raise ValueError("Image must not be empty")
        return value


class Payload(StrictModel):
    """Named texts and images. Result payloads may be empty."""

    texts: dict[Name, Text] = Field(default_factory=dict)
    images: dict[Name, WireImage] = Field(default_factory=dict)

    def to_data(self) -> WebhookEventData:
        return {
            "texts": self.texts.copy(),
            "images": {
                name: {
                    "filename": image.filename,
                    "content_type": image.content_type,
                    "content": base64.b64decode(image.content_base64, validate=True),
                }
                for name, image in self.images.items()
            },
        }


class Submission(Payload):
    """Create an inference event; include at least one named text or image."""

    @model_validator(mode="after")
    def nonempty(self) -> Submission:
        if not self.texts and not self.images:
            raise ValueError("At least one named text or image is required")
        return self


class ResultImage(ImageMetadata):
    content: bytes = Field(min_length=1)


class CallbackResult(StrictModel):
    texts: dict[Name, Text] = Field(default_factory=dict)
    images: dict[Name, ResultImage] = Field(default_factory=dict)

    def to_wire(self, max_items: int, max_bytes: int) -> Payload:
        if len(self.texts) + len(self.images) > max_items:
            raise ValueError("Result exceeds max_items")
        if sum(len(image.content) for image in self.images.values()) > max_bytes:
            raise ValueError("Result exceeds max_result_bytes")
        result = Payload(
            texts=self.texts,
            images={
                name: WireImage(
                    filename=image.filename,
                    content_type=image.content_type,
                    content_base64=base64.b64encode(image.content).decode("ascii"),
                )
                for name, image in self.images.items()
            },
        )
        if len(result.model_dump_json().encode("utf-8")) > max_bytes:
            raise ValueError("Encoded result exceeds max_result_bytes")
        return result


class ErrorInfo(StrictModel):
    code: str
    message: str


class ErrorResponse(StrictModel):
    error: ErrorInfo


class EventResponse(StrictModel):
    event_id: str
    text_count: int
    image_count: int
    status: Literal["pending", "succeeded", "failed", "cancelled"]
    result: Payload | None = None
    error: ErrorInfo | None = None
