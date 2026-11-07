"""Expected HTTP failures, shared by validation and request handling."""

from fastapi import HTTPException


class WebhookError(HTTPException):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(status_code=status, detail=message, headers=headers)
        self.status = status
        self.code = code

    def as_dict(self) -> dict[str, dict[str, str]]:
        return {"error": {"code": self.code, "message": self.detail}}
