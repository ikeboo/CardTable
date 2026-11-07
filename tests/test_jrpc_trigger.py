from __future__ import annotations

import base64
import json
import socket
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from threading import Barrier, Event, Thread
from time import monotonic
from unittest.mock import patch

import cv2
import numpy as np
from jsonschema import validate

import cardtable as c
from cardtable.core.closure import Closure


def request(request_id="1", *, method="trigger", params=None):
    value = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        value["id"] = request_id
    if params is not None or method != "rpc.discover":
        value["params"] = {"texts": {}} if params is None else params
    return value


class JRPCTriggerTest(unittest.TestCase):
    def tearDown(self):
        Closure().close_all()

    @contextmanager
    def connection(self, trigger):
        with socket.create_connection(("127.0.0.1", trigger.port), timeout=3) as client:
            with client.makefile("rwb") as stream:
                yield stream

    def send(self, stream, value):
        stream.write(json.dumps(value).encode() + b"\n")
        stream.flush()

    def receive(self, stream):
        return json.loads(stream.readline())

    def call(self, trigger, value):
        with self.connection(trigger) as stream:
            self.send(stream, value)
            return self.receive(stream)

    @contextmanager
    def serve(self, callback, **options):
        ready = Event()

        class ReadyTrigger(c.JRPCTrigger):
            def start(self):
                super().start()
                ready.set()

        class App(c.Dealer):
            def setup(self):
                self.rpc = ReadyTrigger(port=0, callback=self.handle, **options)

            def handle(self, event: c.TriggerEvent):
                assert event is self.current_event
                callback(event)

        app = App()
        thread = Thread(target=app.start)
        thread.start()
        try:
            self.assertTrue(ready.wait(5))
            yield app.rpc
        finally:
            app.close()
            thread.join(5)
            self.assertFalse(thread.is_alive())

    def test_default_response_and_event_payload(self):
        events = []
        with self.serve(events.append) as trigger:
            value = request("日本語", params={"texts": {"message": "値"}, "image": {}})
            response = self.call(trigger, value)
            self.assertEqual(
                response,
                {
                    "jsonrpc": "2.0",
                    "id": "日本語",
                    "result": {"texts": {"success": True}, "images": {}},
                },
            )
            event = events[0]
            self.assertIs(event.trigger, trigger)
            self.assertEqual(event.data, value)
            self.assertIs(event.texts, event.data["params"]["texts"])
            self.assertIs(event.images, event.data["params"]["image"])
            self.assertNotEqual(event.event_id, value["id"])

    def test_request_png_and_jpeg_are_decoded_before_callback(self):
        image = np.arange(18, dtype=np.uint8).reshape(2, 3, 3)
        encoded, expected = {}, {}
        for name, extension in (("png", ".png"), ("jpeg", ".jpg")):
            _, content = cv2.imencode(extension, image)
            encoded[name] = base64.b64encode(content).decode("ascii")
            # JPEG is lossy: compare to decoding its actual encoded bytes.
            expected[name] = cv2.imdecode(content, cv2.IMREAD_UNCHANGED)
        events = []
        with self.serve(events.append) as trigger:
            value = request(params={"texts": {"prompt": "画像"}, "image": encoded})
            validate(value, trigger.discovery["methods"][0]["x-request-schema"])
            self.assertIn("result", self.call(trigger, value))
            params = events[0].data["params"]
            self.assertIs(events[0].texts, params["texts"])
            self.assertIs(events[0].images, params["image"])
            self.assertEqual(params["texts"], {"prompt": "画像"})
            self.assertEqual(params["image"].keys(), expected.keys())
            for name, decoded in params["image"].items():
                self.assertIsInstance(decoded, np.ndarray)
                np.testing.assert_array_equal(decoded, expected[name])

    def test_omitted_and_empty_images_are_normalized(self):
        events = []
        with self.serve(events.append) as trigger:
            for params in ({"texts": {}}, {"texts": {"prompt": "hello"}, "image": {}}):
                self.assertIn("result", self.call(trigger, request(params=params)))
                self.assertEqual(events[-1].data["params"], {**params, "image": {}})

    def test_invalid_params_are_rejected_atomically(self):
        trigger = c.JRPCTrigger(port=0)
        trigger.start()
        _, png = cv2.imencode(".png", np.zeros((1, 1), np.uint8))
        encoded = base64.b64encode(png).decode("ascii")
        cases = [
            {},
            [],
            [{"texts": {}}],
            {"image": {}},
            {"texts": None},
            {"texts": {"number": 1}},
            {"texts": {}, "image": None},
            {"texts": {}, "images": {}},
            {"texts": {}, "extra": {}},
            {"texts": {}, "image": []},
            {"texts": {}, "image": {"bad": 1}},
            {"texts": {}, "image": {"bad": "%%%"}},
            {"texts": {}, "image": {"bad": base64.b64encode(b"invalid").decode()}},
            {
                "texts": {},
                "image": {"bad": base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()},
            },
            {"texts": {}, "image": {"bad": base64.b64encode(b"\xff\xd8\xff").decode()}},
            {"texts": {}, "image": {"bad": base64.b64encode(b"GIF89a").decode()}},
            {"texts": {}, "image": {"valid": encoded, "bad": "%%%"}},
        ]
        for params in cases:
            with self.subTest(params=params):
                result = self.call(trigger, request(params=params))
                self.assertEqual(result["error"]["code"], -32602)
                self.assertFalse(trigger.message_event.is_set())
                self.assertFalse(trigger._pending)
        value = request()
        del value["params"]
        self.assertEqual(self.call(trigger, value)["error"]["code"], -32602)
        self.assertFalse(trigger.message_event.is_set())

    def test_explicit_text_and_png_response(self):
        image = np.arange(18, dtype=np.uint8).reshape(2, 3, 3)

        def callback(event):
            event.response(
                texts={"answer": "結果"}, images={"image": image}, image_format="png"
            )

        with self.serve(callback) as trigger:
            response = self.call(trigger, request())
            self.assertEqual(response["result"]["texts"], {"answer": "結果"})
            content = base64.b64decode(response["result"]["images"]["image"])
            decoded = cv2.imdecode(
                np.frombuffer(content, np.uint8), cv2.IMREAD_UNCHANGED
            )
            np.testing.assert_array_equal(decoded, image)
            validate(
                response["result"], trigger.discovery["methods"][0]["result"]["schema"]
            )

    def test_jpeg_is_default_and_png_preserves_alpha(self):
        image = np.full((3, 4, 4), (10, 70, 210, 123), dtype=np.uint8)
        for image_format in ("jpg", "png"):
            with self.subTest(image_format=image_format):

                def callback(event):
                    options = {} if image_format == "jpg" else {"image_format": "png"}
                    event.response({}, {"image": image}, **options)

                with self.serve(callback) as trigger:
                    response = self.call(trigger, request())
                    content = base64.b64decode(response["result"]["images"]["image"])
                    validate(
                        response["result"],
                        trigger.discovery["methods"][0]["result"]["schema"],
                    )
                    decoded = cv2.imdecode(
                        np.frombuffer(content, np.uint8), cv2.IMREAD_UNCHANGED
                    )
                    if image_format == "jpg":
                        self.assertTrue(content.startswith(b"\xff\xd8\xff"))
                        self.assertEqual(decoded.shape, (3, 4, 3))
                    else:
                        self.assertTrue(content.startswith(b"\x89PNG\r\n\x1a\n"))
                        np.testing.assert_array_equal(decoded, image)

    def test_invalid_response_format_does_not_consume_request(self):
        def callback(event):
            for image_format in (None, 1, "gif", "jpeg", "JPG"):
                with self.assertRaises((TypeError, ValueError)):
                    event.response({}, {}, image_format=image_format)
            event.response({"answer": "valid"}, {})

        with self.serve(callback) as trigger:
            self.assertEqual(
                self.call(trigger, request())["result"]["texts"], {"answer": "valid"}
            )

    def test_simultaneous_clients_with_identical_rpc_ids_are_isolated(self):
        clients = 12
        barrier = Barrier(clients)

        def callback(event):
            event.response({"value": event.texts["value"]}, {})

        with self.serve(callback, q_size=clients) as trigger:

            def call(index):
                barrier.wait(3)
                return self.call(
                    trigger, request("same", params={"texts": {"value": str(index)}})
                )

            with ThreadPoolExecutor(max_workers=clients) as executor:
                responses = list(executor.map(call, range(clients)))
            for index, response in enumerate(responses):
                self.assertEqual(response["id"], "same")
                self.assertEqual(response["result"]["texts"], {"value": str(index)})
            self.assertFalse(trigger._pending)

    def test_fragmented_and_pipelined_requests(self):
        with self.serve(lambda event: None) as trigger:
            with self.connection(trigger) as stream:
                wire = (
                    json.dumps(
                        request("first", params={"texts": {"value": "日本語"}}),
                        ensure_ascii=False,
                    ).encode()
                    + b"\n"
                )
                for fragment in (wire[:10], wire[10:53], wire[53:]):
                    stream.write(fragment)
                    stream.flush()
                self.send(stream, request("second"))
                self.assertEqual(self.receive(stream)["id"], "first")
                self.assertEqual(self.receive(stream)["id"], "second")

    def test_batch_mixed_invalid_requests_and_notifications(self):
        seen = []
        with self.serve(lambda event: seen.append(event.data)) as trigger:
            result = self.call(
                trigger,
                [
                    request("first"),
                    5,
                    request(None),
                    request("last"),
                    [request("nested")],
                ],
            )
            self.assertEqual(
                [item["id"] for item in result], ["first", None, "last", None]
            )
            self.assertEqual(result[1]["error"]["code"], -32600)
            self.assertEqual(result[3]["error"]["code"], -32600)
            self.assertEqual(len(seen), 3)
            with self.connection(trigger) as stream:
                self.send(stream, [request(None), request(None)])
                self.send(stream, request("after"))
                self.assertEqual(self.receive(stream)["id"], "after")

    def test_notification_has_no_response(self):
        with self.serve(lambda event: None) as trigger:
            with self.connection(trigger) as stream:
                self.send(stream, request(None))
                self.send(stream, request("reply"))
                self.assertEqual(self.receive(stream)["id"], "reply")

    def test_discovery_and_unknown_method_do_not_trigger(self):
        trigger = c.JRPCTrigger(port=0, method="infer")
        trigger.start()
        result = self.call(trigger, request(method="rpc.discover"))
        document = result["result"]
        self.assertEqual(document["openrpc"], "1.3.2")
        schema = document["methods"][0]["x-request-schema"]
        validate(request(method="infer", params={"texts": {"prompt": "hello"}}), schema)
        self.assertEqual(document["methods"][0]["name"], "infer")
        method = document["methods"][0]
        self.assertEqual(method["paramStructure"], "by-name")
        self.assertEqual(
            [(p["name"], p["required"]) for p in method["params"]],
            [("texts", True), ("image", False)],
        )
        self.assertFalse(trigger.message_event.is_set())
        self.assertEqual(self.call(trigger, request())["error"]["code"], -32601)
        self.assertEqual(
            self.call(trigger, request(method="rpc.discover", params=[1]))["error"][
                "code"
            ],
            -32602,
        )
        self.assertFalse(trigger.message_event.is_set())

    def test_malformed_json_invalid_envelopes_and_nonstring_ids(self):
        trigger = c.JRPCTrigger(port=0)
        trigger.start()
        with self.connection(trigger) as stream:
            for body in (b"{\n", b"\xff\n", b'{"x":NaN}\n', b'{"x":1e400}\n'):
                stream.write(body)
                stream.flush()
                self.assertEqual(self.receive(stream)["error"]["code"], -32700)
            for value in (
                [],
                {},
                3,
                {"jsonrpc": "1.0", "method": "trigger"},
                request(1),
                request(True),
                request(params="wrong"),
            ):
                self.send(stream, value)
                self.assertEqual(self.receive(stream)["error"]["code"], -32600)
        self.assertFalse(trigger.message_event.is_set())

    def test_queue_overload_and_busy_return_errors(self):
        for options in ({"q_size": 1}, {"drop_if_busy": True}):
            with self.subTest(options=options):
                trigger = c.JRPCTrigger(port=0, response_timeout=0.08, **options)
                trigger.start()
                self.assertEqual(
                    self.call(trigger, request("first"))["error"]["code"], -32000
                )
                self.assertEqual(
                    self.call(trigger, request("full"))["error"]["message"],
                    "Event queue is full or busy",
                )
                self.assertFalse(trigger._pending)
                trigger.stop()

    def test_callback_failure_and_invalid_image_return_internal_errors(self):
        for callback in (
            lambda event: 1 / 0,
            lambda event: event.response({}, {"bad": np.zeros((2, 2))}),
        ):
            with self.subTest(callback=callback), self.serve(callback) as trigger:
                self.assertEqual(self.call(trigger, request())["error"]["code"], -32603)

    def test_unknown_event_and_duplicate_response_do_not_corrupt_other_requests(self):
        def callback(event):
            with self.assertRaises(RuntimeError):
                replace(event, event_id="unknown").response({}, {})
            event.response({"answer": "first"}, {})
            with self.assertRaises(RuntimeError):
                event.response({"answer": "second"}, {})

        with self.serve(callback) as trigger:
            for _ in range(2):
                self.assertEqual(
                    self.call(trigger, request())["result"]["texts"],
                    {"answer": "first"},
                )

    def test_saved_event_cannot_respond_to_later_request_with_same_rpc_id(self):
        previous = []

        def callback(event):
            if previous:
                with self.assertRaises(RuntimeError):
                    previous[0].response({"value": "stale"}, {})
            event.response(event.texts, {})
            previous.append(event)

        with self.serve(callback) as trigger:
            for value in ("first", "second"):
                response = self.call(
                    trigger, request("same", params={"texts": {"value": value}})
                )
                self.assertEqual(response["result"]["texts"], {"value": value})
        self.assertNotEqual(previous[0].event_id, previous[1].event_id)

    def test_timed_out_request_cannot_respond_to_next_request_with_same_id(self):
        entered, release, finished = Event(), Event(), Event()
        failures = []

        def callback(event):
            if event.texts["value"] == "old":
                entered.set()
                release.wait(3)
                try:
                    event.response({"value": "old"}, {})
                except RuntimeError as exc:
                    failures.append(exc)
                finished.set()
            else:
                event.response({"value": "new"}, {})

        try:
            with self.serve(callback, response_timeout=0.15) as trigger:
                old = self.call(
                    trigger, request("same", params={"texts": {"value": "old"}})
                )
                self.assertTrue(entered.is_set())
                self.assertEqual(old["error"]["message"], "Callback timed out")
                with self.connection(trigger) as stream:
                    self.send(
                        stream, request("same", params={"texts": {"value": "new"}})
                    )
                    self.assertTrue(trigger.message_event.wait(1))
                    release.set()
                    new = self.receive(stream)
                self.assertTrue(finished.wait(2))
                self.assertEqual(new["result"]["texts"], {"value": "new"})
                self.assertEqual(len(failures), 1)
        finally:
            release.set()

    def test_stop_cancels_waiters_and_partial_reads_and_allows_restart(self):
        trigger = c.JRPCTrigger(port=0, response_timeout=60)
        trigger.start()
        worker = trigger._server.thread
        with self.connection(trigger) as partial, self.connection(trigger) as pending:
            partial.write(b'{"jsonrpc":')
            partial.flush()
            self.send(pending, request())
            deadline = monotonic() + 2
            while not trigger.message_event.wait(0.01):
                self.assertLess(monotonic(), deadline)
            started = monotonic()
            trigger.stop()
            self.assertLess(monotonic() - started, 2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(trigger._pending)
        self.assertFalse(trigger.message_event.is_set())
        self.assertTrue(trigger.is_stopped)
        trigger.stop()
        trigger.start()
        new_worker = trigger._server.thread
        trigger.start()
        self.assertIs(trigger._server.thread, new_worker)
        self.assertIn("result", self.call(trigger, request(method="rpc.discover")))

    def test_bind_and_thread_start_failures_are_recoverable(self):
        first = c.JRPCTrigger(port=0)
        first.start()
        second = c.JRPCTrigger(port=first.port)
        with self.assertRaises(OSError):
            second.start()
        self.assertTrue(second.is_stopped)
        first.stop()
        second.start()
        second.stop()
        with patch(
            "cardtable.triggers.jrpc.server.Thread.start",
            side_effect=RuntimeError("start"),
        ):
            with self.assertRaises(RuntimeError):
                second.start()
        second.start()
        self.assertIn("result", self.call(second, request(method="rpc.discover")))

    def test_limits_close_connections_without_enqueuing(self):
        trigger = c.JRPCTrigger(
            port=0, max_request_bytes=100, request_timeout=0.05, max_batch_size=1
        )
        trigger.start()
        self.assertEqual(
            self.call(trigger, [request(), request()])["error"]["code"], -32000
        )
        with self.connection(trigger) as stream:
            stream.write(b"x" * 101 + b"\n")
            stream.flush()
            self.assertEqual(self.receive(stream)["error"]["code"], -32000)
            self.assertEqual(stream.readline(), b"")
        with self.connection(trigger) as stream:
            stream.write(b"{")
            stream.flush()
            self.assertEqual(self.receive(stream)["error"]["code"], -32000)
        self.assertFalse(trigger.message_event.is_set())

    def test_bad_options_do_not_register_components(self):
        before = Closure().objects
        for options in (
            {"port": True},
            {"port": -1},
            {"port": 65536},
            {"method": "rpc.custom"},
            {"host": ""},
            {"response_timeout": float("nan")},
            {"request_timeout": True},
            {"max_request_bytes": 0},
            {"max_batch_size": 0},
            {"callback": lambda event: None},
            {"q_size": 0},
        ):
            with self.subTest(options=options):
                with self.assertRaises((ValueError, TypeError)):
                    c.JRPCTrigger(**options)
        self.assertEqual(Closure().objects, before)


if __name__ == "__main__":
    unittest.main()
