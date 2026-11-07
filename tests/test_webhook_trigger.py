from __future__ import annotations

import copy
import json
import socket
import unittest
from http.client import HTTPConnection
from threading import Event, Thread
from time import monotonic
from unittest.mock import patch

import requests

import cardtable as c
from cardtable.core.closure import Closure
from cardtable.triggers.webhook.documentation import EXAMPLE

MODULE = "cardtable.triggers.webhook"


class WebhookTriggerTest(unittest.TestCase):
    def tearDown(self):
        Closure().close_all()

    def start(self, **options):
        trigger = c.WebhookTrigger(port=0, **options)
        trigger.start()
        return trigger

    def post(self, trigger, **options):
        return requests.post(
            trigger.url, params={"wait": "false"}, timeout=2, **options
        )

    def raw(self, trigger, headers, body=b"", method="POST", path=None):
        connection = HTTPConnection("127.0.0.1", trigger.port, timeout=2)
        try:
            connection.putrequest(method, path or trigger.settings.path + "?wait=false")
            for name, value in headers:
                connection.putheader(name, value)
            connection.endheaders(body)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def finish_one(self, trigger):
        message = trigger._take_message()
        event = c.TriggerEvent(
            trigger=trigger,
            timestamp=message.timestamp,
            data=message.data,
            event_id=message.event_id,
        )
        trigger._callbacks_finished(event, (None,), ())
        trigger._complete_message()

    def test_post_returns_created_resource_and_same_event_identity(self):
        trigger = self.start()
        response = self.post(trigger, json=EXAMPLE)
        self.assertEqual(response.status_code, 201, response.text)
        receipt = response.json()
        self.assertEqual(receipt["text_count"], 2)
        self.assertEqual(receipt["image_count"], 1)
        self.assertEqual(response.headers["Location"], "/events/" + receipt["event_id"])
        fetched = requests.get(
            trigger.base_url + response.headers["Location"], timeout=2
        )
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json(), receipt)
        self.assertEqual(fetched.json()["status"], "pending")
        message = trigger._take_message()
        trigger._complete_message()
        self.assertEqual(message.event_id, receipt["event_id"])
        self.assertEqual(message.data["texts"], EXAMPLE["texts"])
        self.assertIsInstance(message.data["images"]["before"]["content"], bytes)
        self.assertFalse(trigger.drop_if_busy)
        self.assertEqual(trigger.q_size, 10)

    def test_optional_auth_protects_events_and_receipts_but_not_docs(self):
        trigger = self.start(token="test-secret")
        for headers in (
            {},
            {"Authorization": "Bearer wrong"},
            {"Authorization": "Basic test-secret"},
        ):
            response = self.post(trigger, json=EXAMPLE, headers=headers)
            self.assertEqual(response.status_code, 401)
            self.assertIn("Bearer", response.headers["WWW-Authenticate"])
        self.assertFalse(trigger.message_event.is_set())
        headers = {"Authorization": "bearer test-secret"}
        response = self.post(trigger, json=EXAMPLE, headers=headers)
        self.assertEqual(response.status_code, 201)
        url = trigger.base_url + response.headers["Location"]
        self.assertEqual(requests.get(url, timeout=2).status_code, 401)
        self.assertEqual(requests.get(url, headers=headers, timeout=2).status_code, 200)
        for path in ("/docs", "/openapi.json"):
            result = requests.get(trigger.base_url + path, timeout=2)
            self.assertEqual(result.status_code, 200)
            self.assertNotIn("test-secret", result.text)

    def test_validation_is_atomic_and_failed_submissions_do_not_evict_history(self):
        trigger = self.start(history_size=1)
        accepted = self.post(trigger, json={"texts": {"name": "first"}})
        invalid = copy.deepcopy(EXAMPLE)
        invalid["images"]["after"] = {
            "filename": "bad.png",
            "content_type": "image/png",
            "content_base64": "%%",
        }
        response = self.post(trigger, json=invalid)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(trigger._message_queue), 1)
        previous = requests.get(
            trigger.base_url + accepted.headers["Location"], timeout=2
        )
        self.assertEqual(previous.status_code, 200)
        for body in ([], {}, {"texts": {"name": 3}}, {"images": None}):
            self.assertEqual(self.post(trigger, json=body).status_code, 400)

    def test_body_and_item_limits_and_media_type(self):
        trigger = self.start(max_body_bytes=128, max_items=1)
        response = self.post(trigger, json={"texts": {"a": "a", "b": "b"}})
        self.assertEqual(response.status_code, 413)
        response = self.post(trigger, json={"texts": {"a": "x" * 200}})
        self.assertEqual(response.status_code, 413)
        for content_type in ("text/plain", "application/json; charset=shift_jis"):
            response = self.post(
                trigger,
                data=b'{"texts":{"a":"hello"}}',
                headers={"Content-Type": content_type},
            )
            self.assertEqual(response.status_code, 415)
        self.assertFalse(trigger.message_event.is_set())

    def test_malformed_framing_and_oversize_headers_are_rejected(self):
        trigger = self.start()
        cases = [
            ([("Content-Type", "application/json")], 400),
            ([("Content-Length", "-1")], 400),
            (
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", "0"),
                    ("Content-Length", "0"),
                ],
                400,
            ),
            (
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(trigger.settings.max_body_bytes + 1)),
                ],
                413,
            ),
            (
                [
                    ("Content-Length", "0"),
                    ("Content-Type", "application/json"),
                    ("Content-Type", "text/plain"),
                ],
                415,
            ),
        ]
        for headers, expected in cases:
            with self.subTest(headers=headers):
                status, _, body = self.raw(trigger, headers)
                self.assertEqual(status, expected, body)
                if body.startswith(b"{"):
                    self.assertIn("error", json.loads(body))
        self.assertFalse(trigger.message_event.is_set())

    def test_timeout_and_incomplete_body_do_not_create_events(self):
        trigger = self.start(request_timeout=0.1)
        status, _, body = self.raw(
            trigger,
            [
                ("Content-Type", "application/json"),
                ("Content-Length", "100"),
            ],
        )
        self.assertEqual(status, 408, body)
        with socket.create_connection(("127.0.0.1", trigger.port), timeout=2) as client:
            client.sendall(
                b"POST /events HTTP/1.1\r\nHost: localhost\r\n"
                b"Content-Type: application/json\r\nContent-Length: 100\r\n\r\n{}"
            )
            client.shutdown(socket.SHUT_WR)
            with client.makefile("rb") as stream:
                status = stream.readline()
                self.assertTrue(
                    not status or status.startswith(b"HTTP/1.1 400"), status
                )
        self.assertFalse(trigger.message_event.is_set())

    def test_chunked_requests_are_size_limited(self):
        trigger = self.start(max_body_bytes=100)
        headers = {"Content-Type": "application/json"}
        body = json.dumps({"texts": {"prompt": "hello"}}).encode()
        accepted = requests.post(
            trigger.url,
            params={"wait": False},
            data=iter([body[:8], body[8:]]),
            headers=headers,
            timeout=2,
        )
        self.assertEqual(accepted.status_code, 201)
        self.finish_one(trigger)
        large = json.dumps({"texts": {"prompt": "x" * 200}}).encode()
        rejected = requests.post(
            trigger.url,
            params={"wait": False},
            data=iter([large[:60], large[60:]]),
            headers=headers,
            timeout=2,
        )
        self.assertEqual(rejected.status_code, 413)
        self.assertFalse(trigger.message_event.is_set())

    def test_queue_full_and_busy_are_rejected_without_receipts(self):
        for options in ({"q_size": 1}, {"drop_if_busy": True}):
            trigger = self.start(**options)
            first = self.post(trigger, json={"texts": {"n": "first"}})
            self.assertEqual(first.status_code, 201)
            if options.get("drop_if_busy"):
                self.assertIsNotNone(trigger._take_message())
            with self.assertLogs(MODULE + ".trigger", level="WARNING"):
                second = self.post(trigger, json={"texts": {"n": "second"}})
            self.assertEqual(second.status_code, 503)
            self.assertNotIn("event_id", second.json())
            self.assertEqual(len(trigger._history._jobs), 1)
            if options.get("drop_if_busy"):
                trigger._complete_message()
            trigger.stop()

    def test_receipt_eviction_and_custom_collection_path(self):
        trigger = self.start(path="/api/events", history_size=2)
        receipts = []
        for i in range(3):
            receipts.append(self.post(trigger, json={"texts": {"n": str(i)}}))
            self.finish_one(trigger)
        self.assertEqual(
            requests.get(
                trigger.base_url + receipts[0].headers["Location"], timeout=2
            ).status_code,
            404,
        )
        for response in receipts[1:]:
            self.assertTrue(response.headers["Location"].startswith("/api/events/"))
            self.assertEqual(
                requests.get(
                    trigger.base_url + response.headers["Location"], timeout=2
                ).status_code,
                200,
            )
        self.assertEqual(
            requests.post(trigger.base_url + "/events", json={}, timeout=2).status_code,
            404,
        )

    def test_methods_and_head_do_not_create_events(self):
        trigger = self.start()
        for method in ("GET", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"):
            response = requests.request(method, trigger.url, timeout=2)
            self.assertEqual(response.status_code, 405)
            self.assertEqual(response.headers["Allow"], "POST")
        head = requests.head(trigger.base_url + "/docs", timeout=2)
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b"")
        self.assertGreater(int(head.headers["Content-Length"]), 0)
        self.assertFalse(trigger.message_event.is_set())

    def test_docs_and_openapi_reflect_settings_without_exposing_secrets(self):
        trigger = self.start(
            token="never-show-this",
            max_items=7,
            max_body_bytes=4321,
            history_size=3,
            request_timeout=2,
            path="/api/input",
        )
        html = requests.get(trigger.base_url + "/guide", timeout=2)
        self.assertEqual(html.status_code, 200)
        for fragment in (
            "/api/input",
            "4321",
            "7",
            "3",
            "201",
            "推論結果",
            "YOUR_TOKEN",
            "結果取得",
        ):
            self.assertIn(fragment, html.text)
        self.assertNotIn("never-show-this", html.text)
        spec = requests.get(trigger.base_url + "/openapi.json", timeout=2).json()
        self.assertEqual(spec["openapi"], "3.1.0")
        self.assertEqual(spec["servers"][0]["url"], trigger.base_url)
        self.assertIn(
            "swagger-ui", requests.get(trigger.base_url + "/docs", timeout=2).text
        )
        self.assertIn("/api/input/{event_id}", spec["paths"])
        post = spec["paths"]["/api/input"]["post"]
        self.assertEqual(post["security"], [{"HTTPBearer": []}])
        self.assertNotIn("/docs", spec["paths"])
        self.assertIn("4321", spec["info"]["description"])
        self.assertIn("202", post["responses"])
        self.assertIn(
            "result", spec["components"]["schemas"]["EventResponse"]["properties"]
        )

    def test_stop_interrupts_partial_headers_and_partial_body_and_allows_restart(self):
        for request in (
            b"POST /events HTTP/1.1\r\nHost:",
            b"POST /events HTTP/1.1\r\nHost: localhost\r\nContent-Length: 1000\r\n"
            b"Content-Type: application/json\r\n\r\n{}",
        ):
            trigger = self.start(request_timeout=20)
            server, worker = trigger._server, trigger._watch_thread
            with socket.create_connection(
                ("127.0.0.1", trigger.port), timeout=2
            ) as client:
                client.sendall(request)
                deadline = monotonic() + 2
                while not server.runner.server_state.connections:
                    if monotonic() >= deadline:
                        self.fail("HTTP connection was not accepted")
                    Event().wait(0.01)
                started = monotonic()
                trigger.stop()
                self.assertLess(monotonic() - started, 2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(server.socket.fileno(), -1)
            self.assertTrue(trigger.is_stopped)
            trigger.start()
            self.assertEqual(
                self.post(trigger, json={"texts": {"n": "new"}}).status_code, 201
            )
            trigger.stop()

    def test_start_is_idempotent_and_stop_clears_queue_and_receipts(self):
        trigger = self.start()
        server, worker, event_id = trigger._server, trigger._watch_thread, trigger.id
        trigger.start()
        self.assertIs(trigger._server, server)
        response = self.post(trigger, json={"texts": {"n": "first"}})
        trigger.stop()
        trigger.stop()
        self.assertFalse(worker.is_alive())
        self.assertFalse(trigger.message_event.is_set())
        with self.assertRaisesRegex(RuntimeError, "not been started"):
            _ = trigger.url
        trigger.start()
        self.assertEqual(trigger.id, event_id)
        self.assertEqual(
            requests.get(
                trigger.base_url + response.headers["Location"], timeout=2
            ).status_code,
            404,
        )

    def test_start_failure_closes_bound_socket_and_can_be_retried(self):
        trigger = c.WebhookTrigger(port=0)
        with patch(MODULE + ".trigger.Thread") as thread:
            thread.return_value.ident = None
            thread.return_value.start.side_effect = RuntimeError("cannot start")
            with self.assertRaisesRegex(RuntimeError, "cannot start"):
                trigger.start()
        self.assertIsNone(trigger._server)
        self.assertTrue(trigger.is_stopped)
        trigger.start()
        self.assertEqual(
            self.post(trigger, json={"texts": {"n": "ok"}}).status_code, 201
        )

    def test_port_conflict_is_reported_and_can_be_retried(self):
        first = self.start()
        second = c.WebhookTrigger(port=first.port)
        with self.assertRaises(OSError):
            second.start()
        self.assertTrue(second.is_stopped)
        first.stop()
        second.start()
        self.assertEqual(
            self.post(second, json={"texts": {"n": "ok"}}).status_code, 201
        )

    def test_bad_options_do_not_register_components(self):
        baseline = Closure().objects
        for options, error in (
            ({"port": True}, TypeError),
            ({"port": -1}, ValueError),
            ({"port": 65536}, ValueError),
            ({"host": ""}, ValueError),
            ({"host": "http://localhost"}, ValueError),
            ({"host": None}, TypeError),
            ({"path": "events"}, ValueError),
            ({"path": "/docs"}, ValueError),
            ({"path": "/events/"}, ValueError),
            ({"path": "/a/../b"}, ValueError),
            ({"max_body_bytes": 0}, ValueError),
            ({"max_items": True}, TypeError),
            ({"max_items": 0}, ValueError),
            ({"history_size": 0}, ValueError),
            ({"max_result_bytes": 0}, ValueError),
            ({"response_timeout": 0}, ValueError),
            ({"token": ""}, ValueError),
            ({"token": "secret\n"}, ValueError),
            ({"token": 1}, TypeError),
            ({"request_timeout": 0}, ValueError),
            ({"request_timeout": float("nan")}, ValueError),
            ({"request_timeout": True}, TypeError),
            ({"q_size": 0}, ValueError),
            ({"callback": lambda event: None}, TypeError),
        ):
            with self.subTest(options=options):
                with self.assertRaises(error):
                    c.WebhookTrigger(**options)
        self.assertEqual(Closure().objects, baseline)

    def test_flow_receives_named_payload_and_joins_http_worker_on_close(self):
        ready, received = Event(), Event()
        events = []

        class ReadyWebhook(c.WebhookTrigger):
            def start(self):
                super().start()
                ready.set()

        class App(c.Dealer):
            def setup(self):
                self.webhook = ReadyWebhook(port=0, callback=self.on_received)

            def on_received(self, event: c.TriggerEvent):
                events.append((event, self.current_event))
                received.set()

        app = App()
        thread = Thread(target=app.start)
        thread.start()
        try:
            self.assertTrue(ready.wait(3))
            worker = app.webhook._watch_thread
            response = self.post(app.webhook, json=EXAMPLE)
            self.assertEqual(response.status_code, 201)
            self.assertTrue(received.wait(3))
        finally:
            app.close()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertFalse(worker.is_alive())
        event, current = events[0]
        self.assertIs(event, current)
        self.assertIs(event.trigger, app.webhook)
        self.assertEqual(event.event_id, response.json()["event_id"])
        self.assertEqual(event.data["texts"]["language"], "日本語")
        self.assertTrue(
            event.data["images"]["before"]["content"].startswith(b"\x89PNG")
        )


if __name__ == "__main__":
    unittest.main()
