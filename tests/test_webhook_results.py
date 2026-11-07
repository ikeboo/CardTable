from __future__ import annotations

import base64
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event, Thread
from unittest.mock import patch

import requests

import cardtable as c
from cardtable.core.closure import Closure
from cardtable.triggers.webhook.documentation import EXAMPLE


class WebhookResultsTest(unittest.TestCase):
    def tearDown(self):
        Closure().close_all()

    @contextmanager
    def serve(self, callback, **options):
        ready = Event()

        class ReadyWebhook(c.WebhookTrigger):
            def start(self):
                super().start()
                ready.set()

        class App(c.Dealer):
            def setup(self):
                self.webhook = ReadyWebhook(port=0, callback=self.infer, **options)

            def infer(self, event: c.TriggerEvent):
                return callback(event)

        app = App()
        thread = Thread(target=app.start)
        thread.start()
        try:
            self.assertTrue(ready.wait(5))
            yield app.webhook
        finally:
            app.close()
            thread.join(5)
            self.assertFalse(thread.is_alive())

    def test_post_returns_named_inference_texts_and_multiple_images(self):
        def infer(event):
            image = event.data["images"]["before"]
            return {
                "texts": {
                    "answer": "推論結果",
                    "input": event.data["texts"]["language"],
                },
                "images": {"mask": image, "annotated": image},
            }

        with self.serve(infer) as webhook:
            response = requests.post(webhook.url, json=EXAMPLE, timeout=3)
            self.assertEqual(response.status_code, 201, response.text)
            body = response.json()
            self.assertEqual(body["status"], "succeeded")
            self.assertEqual(
                body["result"]["texts"], {"answer": "推論結果", "input": "日本語"}
            )
            for name in ("mask", "annotated"):
                image = body["result"]["images"][name]
                self.assertEqual(image["content_type"], "image/png")
                self.assertEqual(
                    base64.b64decode(image["content_base64"]),
                    base64.b64decode(EXAMPLE["images"]["before"]["content_base64"]),
                )
                self.assertNotIn("content", image)
            url = webhook.base_url + response.headers["Location"]
            self.assertEqual(requests.get(url, timeout=2).json(), body)

    def test_wait_timeout_returns_pending_then_result_without_cancelling_inference(
        self,
    ):
        release = Event()

        def infer(event):
            release.wait(3)
            return {"texts": {"answer": "done"}}

        with self.serve(infer, response_timeout=0.05) as webhook:
            try:
                response = requests.post(
                    webhook.url, json={"texts": {"prompt": "run"}}, timeout=2
                )
                self.assertEqual(response.status_code, 202)
                self.assertEqual(response.json()["status"], "pending")
                url = webhook.base_url + response.headers["Location"]
                self.assertEqual(
                    requests.get(url, timeout=2).json()["status"], "pending"
                )
                job = webhook._history._jobs[response.json()["event_id"]]
                release.set()
                self.assertEqual(job.done.result(2).status, "succeeded")
                result = requests.get(url, timeout=2).json()
                self.assertEqual(result["result"]["texts"]["answer"], "done")
            finally:
                release.set()

    def test_wait_false_returns_before_inference_finishes(self):
        release, entered = Event(), Event()

        def infer(event):
            entered.set()
            release.wait(3)
            return {"texts": {"answer": "done"}}

        with self.serve(infer) as webhook:
            try:
                response = requests.post(
                    webhook.url,
                    params={"wait": False},
                    json={"texts": {"prompt": "run"}},
                    timeout=2,
                )
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json()["status"], "pending")
                self.assertTrue(entered.wait(2))
            finally:
                release.set()

    def test_callback_failure_is_reported_and_later_requests_still_work(self):
        def infer(event):
            if event.data["texts"]["prompt"] == "fail":
                raise ValueError("Inference could not run")
            return {"texts": {"answer": "success"}}

        with self.serve(infer) as webhook:
            failed = requests.post(
                webhook.url, json={"texts": {"prompt": "fail"}}, timeout=2
            )
            self.assertEqual(failed.status_code, 500)
            self.assertEqual(failed.json()["status"], "failed")
            self.assertEqual(failed.json()["error"]["code"], "inference_failed")
            self.assertIn("could not run", failed.json()["error"]["message"])
            read = requests.get(
                webhook.base_url + failed.headers["Location"], timeout=2
            )
            self.assertEqual(read.status_code, 200)
            self.assertEqual(read.json()["status"], "failed")
            succeeded = requests.post(
                webhook.url, json={"texts": {"prompt": "ok"}}, timeout=2
            )
            self.assertEqual(succeeded.json()["result"]["texts"]["answer"], "success")

    def test_none_return_is_a_successful_empty_result(self):
        with self.serve(lambda event: None) as webhook:
            result = requests.post(
                webhook.url, json={"texts": {"prompt": "run"}}, timeout=2
            ).json()
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(result["result"], {"texts": {}, "images": {}})

    def test_invalid_or_oversized_results_are_reported(self):
        for output, options in (
            ("wrong shape", {}),
            ({"texts": {"answer": "x" * 1000}}, {"max_result_bytes": 100}),
            ({"texts": {"a": "a", "b": "b"}}, {"max_items": 1}),
            (
                {
                    "images": {
                        "mask": {
                            "filename": "mask.png",
                            "content_type": "image/png",
                            "content": b"",
                        }
                    }
                },
                {},
            ),
        ):
            with self.subTest(output=repr(output)[:100]):
                with self.serve(lambda event: output, **options) as webhook:
                    with self.assertLogs(
                        "cardtable.triggers.webhook.trigger", level="WARNING"
                    ):
                        response = requests.post(
                            webhook.url, json={"texts": {"prompt": "run"}}, timeout=2
                        )
                    self.assertEqual(response.status_code, 500)
                    self.assertEqual(response.json()["error"]["code"], "invalid_result")

    def test_pending_jobs_are_not_evicted_and_completed_results_are(self):
        release = Event()

        def infer(event):
            if event.data["texts"]["prompt"] == "hold":
                release.wait(3)
            return {"texts": {"answer": "done"}}

        with self.serve(infer, history_size=1) as webhook:
            try:
                first = requests.post(
                    webhook.url,
                    params={"wait": False},
                    json={"texts": {"prompt": "hold"}},
                    timeout=2,
                )
                second = requests.post(
                    webhook.url,
                    params={"wait": False},
                    json={"texts": {"prompt": "next"}},
                    timeout=2,
                )
                self.assertEqual(second.status_code, 503)
                self.assertEqual(second.json()["error"]["code"], "history_full")
                self.assertEqual(
                    requests.get(
                        webhook.base_url + first.headers["Location"], timeout=2
                    ).status_code,
                    200,
                )
                job = webhook._history._jobs[first.json()["event_id"]]
                release.set()
                job.done.result(2)
                third = requests.post(
                    webhook.url, json={"texts": {"prompt": "next"}}, timeout=2
                )
                self.assertEqual(third.status_code, 201)
                self.assertEqual(
                    requests.get(
                        webhook.base_url + first.headers["Location"], timeout=2
                    ).status_code,
                    404,
                )
            finally:
                release.set()

    def test_concurrent_clients_receive_their_own_results(self):
        with self.serve(
            lambda event: {"texts": {"answer": event.data["texts"]["prompt"].upper()}}
        ) as webhook:

            def request(index):
                return requests.post(
                    webhook.url,
                    json={"texts": {"prompt": f"request-{index}"}},
                    timeout=3,
                )

            with ThreadPoolExecutor(max_workers=4) as executor:
                responses = list(executor.map(request, range(4)))
            self.assertEqual(
                len({response.json()["event_id"] for response in responses}), 4
            )
            for index, response in enumerate(responses):
                self.assertEqual(response.status_code, 201)
                self.assertEqual(
                    response.json()["result"]["texts"]["answer"], f"REQUEST-{index}"
                )

    def test_stop_releases_waiting_http_client_with_cancelled_status(self):
        webhook = c.WebhookTrigger(port=0, response_timeout=30)
        webhook.start()
        accepted, finished = Event(), Event()
        original = webhook._accept
        responses = []

        def accept(payload):
            job = original(payload)
            accepted.set()
            return job

        def request():
            try:
                responses.append(
                    requests.post(
                        webhook.url, json={"texts": {"prompt": "run"}}, timeout=3
                    )
                )
            finally:
                finished.set()

        with patch.object(webhook, "_accept", side_effect=accept):
            client = Thread(target=request)
            client.start()
            self.assertTrue(accepted.wait(2))
            webhook.stop()
            self.assertTrue(finished.wait(2))
            client.join(2)
        self.assertEqual(responses[0].status_code, 503)
        self.assertEqual(responses[0].json()["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
