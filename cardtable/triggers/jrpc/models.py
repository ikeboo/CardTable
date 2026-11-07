"""Fixed request params and conversion from wire images to OpenCV arrays."""

import base64

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field


class RequestParams(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    texts: dict[str, str]
    image: dict[str, str] = Field(default_factory=dict)

    def to_data(self) -> dict:
        images = {}
        for name, encoded in self.image.items():
            content = base64.b64decode(encoded, validate=True)
            if not content.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")):
                raise ValueError("image must contain base64 PNG or JPEG data")
            image = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_UNCHANGED)
            if image is None:
                raise ValueError("image could not be decoded")
            images[name] = image
        return {"texts": dict(self.texts), "image": images}

    @classmethod
    def wire_schema(cls) -> dict:
        schema = cls.model_json_schema()
        schema["properties"]["image"]["additionalProperties"].update(
            contentEncoding="base64",
            anyOf=[
                {"contentMediaType": "image/png"},
                {"contentMediaType": "image/jpeg"},
            ],
        )
        return schema
