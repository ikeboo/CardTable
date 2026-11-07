import unittest
from concurrent.futures import wait
from threading import Event, Thread
from unittest.mock import patch

import numpy as np

from cardtable import Dealer, TriggerEvent, WebImageAcquirer
from cardtable.core.closure import Closure
from cardtable.data_classes.trigger_message import TriggerMessage
from test_flow import DummyTrigger


class WebImageAcquirerTest(unittest.TestCase):
    def tearDown(self):
        Closure().close_all()

    def test_results_timeout_and_worker_failure(self):
        service = WebImageAcquirer()
        image = np.zeros((2, 2, 3), dtype=np.uint8)
        with patch.object(service, "acquire_image", side_effect=[image, ValueError("bad")]):
            service.start()
            first = service.submit("one", timeout=1)
            self.assertIs(service.result(first, timeout=1)[1], image)
            second = service.submit("two", timeout=1)
            with self.assertRaisesRegex(RuntimeError, "worker failed"):
                service.result(second, timeout=1)
            with self.assertRaises(TypeError):
                service.result()
        service.stop()
        with self.assertRaisesRegex(RuntimeError, "stopped"):
            service.submit("after stop", timeout=0)

    def test_get_submits_url_and_returns_image(self):
        service = WebImageAcquirer()
        image = np.zeros((1, 1))
        with patch.object(service, "acquire_image", return_value=image) as acquire:
            service.start()
            self.assertEqual(service.get("url", timeout=1), (True, image))
            acquire.assert_called_once_with("url")

    def test_concurrent_requests_receive_their_own_results(self):
        service = WebImageAcquirer()
        entered, release = Event(), Event()
        images = {name: np.full((1, 1), value) for value, name in enumerate(("a", "b"))}

        def acquire(url):
            if url == "a":
                entered.set()
                release.wait(2)
            return images[url]

        results = {}
        with patch.object(service, "acquire_image", side_effect=acquire):
            service.start()
            a = Thread(target=lambda: results.update(a=service.execute("a", timeout=2)))
            b = Thread(target=lambda: results.update(b=service.execute("b", timeout=2)))
            a.start()
            self.assertTrue(entered.wait(1))
            b.start()
            release.set()
            a.join(2)
            b.join(2)
            self.assertIs(results["a"][1], images["a"])
            self.assertIs(results["b"][1], images["b"])

    def test_get_matches_future_when_read_in_reverse_order(self):
        service = WebImageAcquirer()
        images = {name: np.full((1, 1), value) for value, name in enumerate(("a", "b"))}
        with patch.object(service, "acquire_image", side_effect=images.get):
            service.start()
            first = service.submit("a", timeout=1)
            second = service.submit("b", timeout=1)
            self.assertIs(service.result(second, timeout=1)[1], images["b"])
            self.assertIs(service.result(first, timeout=1)[1], images["a"])

    def test_cancelled_queued_request_frees_capacity(self):
        service = WebImageAcquirer()
        entered, release = Event(), Event()

        def acquire(url):
            if url == "active":
                entered.set()
                release.wait(2)
            return None

        with patch.object(service, "acquire_image", side_effect=acquire) as acquire_mock:
            service.start()
            active = service.submit("active")
            self.assertTrue(entered.wait(1))
            queued = service.submit("queued")
            self.assertTrue(queued.cancel())
            self.assertIn(queued, wait([queued], timeout=0).done)
            following = service.submit("following", timeout=0)
            release.set()
            service.result(active, timeout=1)
            service.result(following, timeout=1)
            self.assertEqual([call.args[0] for call in acquire_mock.call_args_list],
                             ["active", "following"])

    def test_timed_out_result_is_discarded(self):
        service = WebImageAcquirer()
        entered, release = Event(), Event()
        image = np.zeros((1, 1))

        def acquire(url):
            if url == "slow":
                entered.set()
                release.wait(2)
                return None
            return image

        with patch.object(service, "acquire_image", side_effect=acquire):
            service.start()
            future = service.submit("slow")
            self.assertTrue(entered.wait(1))
            with self.assertRaises(TimeoutError):
                service.result(future, timeout=0)
            self.assertTrue(future.cancelled())
            release.set()
            self.assertIs(service.execute("next", timeout=2)[1], image)

    def test_shutdown_wakes_blocked_producer_and_consumer(self):
        service = WebImageAcquirer()
        entered, release = Event(), Event()

        def acquire(url):
            entered.set()
            release.wait(2)
            return None

        errors = []

        def blocked(operation):
            try:
                operation()
            except RuntimeError as error:
                errors.append(str(error))

        with patch.object(service, "acquire_image", side_effect=acquire):
            service.start()
            active = service.submit("active")
            self.assertTrue(entered.wait(1))
            service.submit("queued")
            with self.assertRaises(TimeoutError):
                service.submit("full", timeout=0)
            producer = Thread(target=blocked, args=(lambda: service.submit("extra"),))
            consumer = Thread(target=blocked, args=(lambda: service.result(active),))
            producer.start()
            consumer.start()
            try:
                service.request_stop()
                producer.join(1)
                consumer.join(1)
                self.assertFalse(producer.is_alive())
                self.assertFalse(consumer.is_alive())
                self.assertEqual(len(errors), 2)
            finally:
                release.set()
                service.stop()

    def test_flow_shutdown_wakes_callback_waiting_for_service(self):
        entered, release, waiting, returned = Event(), Event(), Event(), Event()

        class App(Dealer):
            def setup(self):
                self.service = WebImageAcquirer()
                self.trigger = DummyTrigger(callback=self.callback)

            def callback(self, event: TriggerEvent):
                future = self.service.submit("url")
                waiting.set()
                try:
                    self.service.result(future)
                except RuntimeError:
                    returned.set()

        app = App()

        def acquire(url):
            entered.set()
            release.wait(3)
            return None

        with patch.object(app.service, "acquire_image", side_effect=acquire):
            app.service.start()
            app.trigger._set_event(TriggerMessage(0, None))
            app._dispatch_messages()
            self.assertTrue(waiting.wait(1))
            self.assertTrue(entered.wait(1))
            closer = Thread(target=app.close)
            closer.start()
            try:
                self.assertTrue(returned.wait(1))
                self.assertTrue(app.is_closing())
                self.assertTrue(app.wait_for_close(0))
            finally:
                release.set()
                closer.join(2)
            self.assertFalse(closer.is_alive())


if __name__ == "__main__":
    unittest.main()
