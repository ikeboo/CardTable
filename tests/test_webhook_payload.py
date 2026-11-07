import asyncio
import base64
import json
import unittest

from pydantic import ValidationError

from cardtable.triggers.webhook.documentation import EXAMPLE
from cardtable.triggers.webhook.errors import WebhookError
from cardtable.triggers.webhook.history import Job, JobHistory
from cardtable.triggers.webhook.limits import StrictRequest
from cardtable.triggers.webhook.models import EventResponse, Submission


def decode_payload(body, max_items):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = StrictRequest({"type": "http"}, receive)
    try:
        submission = Submission.model_validate(asyncio.run(request.json()))
    except ValidationError as cause:
        raise WebhookError(400, "invalid_payload", "Invalid payload") from cause
    if len(submission.texts) + len(submission.images) > max_items:
        raise WebhookError(413, "too_many_items", "Too many items")
    return submission.to_data()


class WebhookPayloadTest(unittest.TestCase):
    def test_named_texts_and_images_are_decoded_without_mutating_input(self):
        image = {
            "filename": "日本語.png",
            "content_type": "IMAGE/PNG",
            "content_base64": base64.b64encode(b"image bytes").decode("ascii"),
        }
        document = {
            "texts": {
                "instruction": "比較してください",
                "language": "日本語",
                "empty": "",
            },
            "images": {"before": image, "after": image},
        }
        decoded = decode_payload(json.dumps(document).encode(), max_items=5)
        self.assertEqual(decoded["texts"], document["texts"])
        for name in ("before", "after"):
            self.assertEqual(
                decoded["images"][name],
                {
                    "filename": "日本語.png",
                    "content_type": "image/png",
                    "content": b"image bytes",
                },
            )
        self.assertIsNot(decoded["images"]["before"], decoded["images"]["after"])
        self.assertIn("content_base64", image)

    def test_either_collection_can_be_omitted(self):
        self.assertEqual(decode_payload(b'{"texts":{"note":"hello"}}', 1)["images"], {})
        result = decode_payload(json.dumps({"images": EXAMPLE["images"]}).encode(), 1)
        self.assertEqual(result["texts"], {})
        self.assertTrue(result["images"]["before"]["content"].startswith(b"\x89PNG"))

    def test_invalid_payloads_are_rejected(self):
        image = EXAMPLE["images"]["before"]
        cases = [
            b"",
            b"not json",
            b"\xff",
            b"[]",
            b"null",
            b"{}",
            b'{"texts":{},"images":{}}',
            b'{"texts":null}',
            b'{"texts":["x"]}',
            b'{"images":[]}',
            b'{"texts":{"x":1}}',
            b'{"texts":{"":"x"}}',
            b'{"texts":{"x":NaN}}',
            b'{"texts":{"x":"\\ud800"}}',
            b'{"texts":{"x":"a","x":"b"}}',
            b'{"texts":{"x":"a"},"texts":{"y":"b"}}',
            b'{"texts":{"x":"a"},"unknown":true}',
            b'{"images":{"x":null}}',
        ]
        cases.append(b'{"texts":{"n":' + b"1" * 5000 + b"}}")
        for change in (
            {"content_base64": "%%%"},
            {"content_base64": ""},
            {"content_base64": "data:image/png;base64,YQ=="},
            {"content_base64": "Y Q=="},
            {"content_base64": "こんにちは"},
            {"content_base64": 123},
            {"filename": ""},
            {"filename": "\ud800"},
            {"extra": "value"},
        ):
            cases.append(json.dumps({"images": {"x": {**image, **change}}}).encode())
        cases.append(json.dumps({"images": {"": image}}).encode())
        cases.append(json.dumps({"images": {"x": {"filename": "x"}}}).encode())
        for body in cases:
            with self.subTest(body=body[:120]):
                with self.assertRaises(WebhookError) as error:
                    decode_payload(body, 32)
                self.assertEqual(error.exception.status, 400)

    def test_item_limit_counts_both_collections_before_decoding_images(self):
        document = {"texts": {"a": "a", "b": "b"}, "images": EXAMPLE["images"]}
        with self.assertRaises(WebhookError) as error:
            decode_payload(json.dumps(document).encode(), 2)
        self.assertEqual(error.exception.status, 413)
        self.assertEqual(error.exception.code, "too_many_items")

    def test_non_image_media_type_is_rejected(self):
        document = {
            "images": {
                "file": {
                    "filename": "file",
                    "content_type": "text/plain",
                    "content_base64": "YQ==",
                }
            }
        }
        with self.assertRaises(WebhookError) as error:
            decode_payload(json.dumps(document).encode(), 32)
        self.assertEqual(error.exception.status, 400)

    def test_history_preserves_pending_jobs_and_evicts_completed_results(self):
        history = JobHistory(2)

        def job(name):
            return Job(
                EventResponse(
                    event_id=name, text_count=1, image_count=0, status="pending"
                )
            )

        history.add(job("one"))
        history.add(job("two"))
        self.assertFalse(history.can_add())
        with self.assertRaisesRegex(RuntimeError, "Pending"):
            history.add(job("three"))
        history.finish("one", None, None)
        self.assertTrue(history.can_add())
        history.add(job("three"))
        self.assertIsNone(history.get("one"))
        self.assertEqual(history.get("two").status, "pending")
        history.cancel_pending()
        self.assertEqual(history.get("two").status, "cancelled")
        history.finish("two", None, None)
        self.assertEqual(history.get("two").status, "cancelled")
        history.clear()
        self.assertIsNone(history.get("three"))


if __name__ == "__main__":
    unittest.main()
