import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock, Thread
from unittest.mock import Mock, patch

import numpy as np

from cardtable import Camera
from cardtable.core.closure import Closure


class CameraTest(unittest.TestCase):
    def tearDown(self):
        Closure().close_all()

    @patch("cardtable.services.camera.cv2.VideoCapture")
    def test_concurrent_execute_serializes_reads_and_returns_each_frame(self, video_capture):
        count = 8
        barrier = Barrier(count)
        lock = Lock()
        active = 0
        peak = 0
        frames = [np.full((1, 1), value) for value in range(count)]
        capture = video_capture.return_value
        capture.isOpened.return_value = True

        def read():
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                frame = frames[capture.read.call_count - 1]
            with lock:
                active -= 1
            return True, frame

        capture.read.side_effect = read
        camera = Camera()
        camera.start()

        def execute():
            barrier.wait(timeout=2)
            return camera.execute(timeout=3)

        with ThreadPoolExecutor(max_workers=count) as pool:
            results = list(pool.map(lambda _: execute(), range(count)))

        self.assertEqual(peak, 1)
        self.assertEqual(sorted(int(frame[0, 0]) for frame in results), list(range(count)))
        self.assertEqual(capture.read.call_count, count)

    @patch("cardtable.services.camera.cv2.VideoCapture")
    def test_camera_opens_reads_and_releases(self, video_capture):
        frame = np.zeros((2, 3, 3), dtype=np.uint8)
        capture = Mock()
        capture.isOpened.return_value = True
        capture.read.return_value = (True, frame)
        video_capture.return_value = capture
        camera = Camera(0)

        camera.start()
        result = camera.get()
        camera.stop()

        video_capture.assert_called_once_with(0)
        self.assertIs(result, frame)
        capture.release.assert_called_once_with()

    @patch("cardtable.services.camera.cv2.VideoCapture")
    def test_request_futures_keep_frames_matched_in_reverse_order(self, video_capture):
        frames = [np.full((1, 1), value) for value in (1, 2)]
        capture = video_capture.return_value
        capture.isOpened.return_value = True
        capture.read.side_effect = [(True, frame) for frame in frames]
        camera = Camera()
        camera.start()
        first = camera.submit(timeout=1)
        second = camera.submit(timeout=1)
        self.assertIs(camera.result(second, timeout=1), frames[1])
        self.assertIs(camera.result(first, timeout=1), frames[0])

    @patch("cardtable.services.camera.cv2.VideoCapture")
    def test_timeout_discards_frame_and_shutdown_wakes_waiter(self, video_capture):
        entered, release = Event(), Event()
        frame = np.zeros((1, 1))
        capture = video_capture.return_value
        capture.isOpened.return_value = True

        def read():
            entered.set()
            release.wait(3)
            return True, frame

        capture.read.side_effect = read
        camera = Camera()
        camera.start()
        first = camera.submit()
        self.assertTrue(entered.wait(1))
        with self.assertRaises(TimeoutError):
            camera.result(first, timeout=0)
        self.assertTrue(first.cancelled())
        second = camera.submit()
        errors = []

        def wait_for_result():
            try:
                camera.result(second)
            except RuntimeError as error:
                errors.append(str(error))

        waiter = Thread(target=wait_for_result)
        waiter.start()
        try:
            camera.request_stop()
            waiter.join(1)
            self.assertFalse(waiter.is_alive())
            self.assertEqual(len(errors), 1)
        finally:
            release.set()
            camera.stop()
        capture.release.assert_called_once_with()

    @patch("cardtable.services.camera.cv2.VideoCapture")
    def test_camera_reports_open_and_read_failures(self, video_capture):
        capture = Mock()
        capture.isOpened.return_value = False
        video_capture.return_value = capture

        with self.assertRaisesRegex(RuntimeError, "failed to open"):
            Camera(0).start()

        capture.isOpened.return_value = True
        capture.read.return_value = (False, None)
        camera = Camera(0)
        camera.start()
        with self.assertRaisesRegex(RuntimeError, "failed to read"):
            camera.get()


if __name__ == "__main__":
    unittest.main()
