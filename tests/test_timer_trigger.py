import unittest
from unittest.mock import patch

from cardtable.triggers._trigger import Trigger
from cardtable.triggers.timer_trigger import TimerTrigger


class TimerTriggerTest(unittest.TestCase):
    def tearDown(self):
        trigger = getattr(self, "trigger", None)
        if trigger is not None:
            trigger.stop()

    def test_is_a_trigger_and_fires_after_the_interval(self):
        self.trigger = TimerTrigger(10)

        self.assertIsInstance(self.trigger, Trigger)
        self.trigger.start()

        self.assertTrue(self.trigger.message_event.wait(timeout=0.5))
        message = self.trigger.message_event.get_message()
        self.assertEqual(message.data, {"interval_ms": 10})
        self.assertGreater(message.timestamp, 0)

    def test_stop_interrupts_the_wait(self):
        self.trigger = TimerTrigger(1_000)
        self.trigger.start()

        self.trigger.stop()

        self.assertTrue(self.trigger.is_stopped)
        self.assertFalse(self.trigger._watch_thread.is_alive())
        self.assertFalse(self.trigger.message_event.is_set())

    def test_can_be_restarted_after_stop(self):
        self.trigger = TimerTrigger(10)
        self.trigger.start()
        self.trigger.stop()

        self.trigger.start()

        self.assertFalse(self.trigger.is_stopped)
        self.assertTrue(self.trigger.message_event.wait(timeout=0.5))

    def test_interval_must_be_positive(self):
        with self.assertRaises(ValueError):
            TimerTrigger(0)

    def test_accepts_trigger_queue_options(self):
        self.trigger = TimerTrigger(10, drop_if_busy=False, q_size=3)

        self.assertFalse(self.trigger.drop_if_busy)
        self.assertEqual(self.trigger.q_size, 3)

    def test_compensates_for_time_spent_firing_event(self):
        self.trigger = TimerTrigger(100)
        waits = []

        def wait(timeout):
            waits.append(timeout)
            return len(waits) == 3

        self.trigger._stop_event.wait = wait
        with patch(
            "cardtable.triggers.timer_trigger.perf_counter_ns",
            side_effect=[
                0,
                0,
                130_000_000,
                130_000_000,
                230_000_000,
                230_000_000,
            ],
        ):
            self.trigger.watching_loop()

        self.assertAlmostEqual(waits[0], 0.1)
        self.assertAlmostEqual(waits[1], 0.07)
        self.assertAlmostEqual(waits[2], 0.07)

    def test_skips_elapsed_intervals_after_a_long_delay(self):
        self.trigger = TimerTrigger(100)
        waits = []

        def wait(timeout):
            waits.append(timeout)
            return len(waits) == 2

        self.trigger._stop_event.wait = wait
        with patch(
            "cardtable.triggers.timer_trigger.perf_counter_ns",
            side_effect=[0, 0, 350_000_000, 350_000_000],
        ):
            self.trigger.watching_loop()

        self.assertAlmostEqual(waits[0], 0.1)
        self.assertAlmostEqual(waits[1], 0.05)


if __name__ == "__main__":
    unittest.main()
