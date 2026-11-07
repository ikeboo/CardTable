from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from unittest.mock import patch
from zoneinfo import ZoneInfo

import cardtable as c
from cardtable.core.closure import Closure

MODULE = "cardtable.triggers.schedule_trigger"
UTC = timezone.utc
BASE = datetime(2026, 11, 2, 8, tzinfo=UTC)  # Monday


class ScheduleTriggerTest(unittest.TestCase):
    def tearDown(self):
        Closure().close_all()

    def make(self, schedules="0 9 * * *", **options):
        options.setdefault("timezone", "UTC")
        with patch.object(
            c.ScheduleTrigger, "get_timestamp", return_value=BASE.timestamp()
        ):
            return c.ScheduleTrigger(schedules, **options)

    def prime(self, trigger, base=BASE):
        with trigger._state_lock:
            trigger._prepare(base.timestamp())

    def test_normalizes_duplicates_and_preserves_expression_order(self):
        expressions = [" 0  9 * * * ", "30 12 * * *", "0 9 * * *"]
        trigger = self.make(expressions)
        expressions.append("0 18 * * *")
        self.assertEqual(trigger.schedules, ("0 9 * * *", "30 12 * * *"))
        self.assertEqual(self.make().schedules, ("0 9 * * *",))
        self.assertFalse(trigger.drop_if_busy)
        self.assertEqual(trigger.q_size, 100)

    def test_defaults_to_machine_zone_with_seasonal_offsets(self):
        local = ZoneInfo("America/New_York")
        with patch(f"{MODULE}.get_localzone", return_value=local) as detect:
            trigger = self.make(timezone=None)
        detect.assert_called_once_with()
        self.assertIs(trigger.timezone, local)
        for month, expected_offset in ((1, -5), (7, -4)):
            base = datetime(2026, month, 2, 8, tzinfo=local)
            next_time = trigger._next_after("0 9 * * *", base.timestamp())
            scheduled = datetime.fromtimestamp(next_time, local)
            self.assertEqual(scheduled.hour, 9)
            self.assertEqual(scheduled.utcoffset(), timedelta(hours=expected_offset))

    def test_explicit_zone_does_not_use_machine_zone(self):
        with patch(f"{MODULE}.get_localzone") as detect:
            trigger = self.make(timezone="Asia/Tokyo")
        detect.assert_not_called()
        base = datetime(2026, 11, 2, 8, tzinfo=ZoneInfo("Asia/Tokyo"))
        self.prime(trigger, base)
        message = trigger._check_due(base.timestamp() + 3600)
        self.assertEqual(message.data["scheduled_at"].hour, 9)
        self.assertEqual(message.data["scheduled_at"].utcoffset(), timedelta(hours=9))

    def test_each_time_fires_and_overlaps_are_combined(self):
        expressions = ("0 9 * * *", "0 9 * * 1-5", "30 12 * * *")
        trigger = self.make(expressions)
        self.prime(trigger)
        self.assertIsNone(trigger._check_due(BASE.timestamp() + 3599))
        first = trigger._check_due(BASE.timestamp() + 3600)
        self.assertEqual(
            first.data,
            {"scheduled_at": BASE.replace(hour=9), "schedules": expressions[:2]},
        )
        self.assertEqual(first.timestamp, BASE.timestamp() + 3600)
        self.assertIsNone(trigger._check_due(first.timestamp))
        second = trigger._check_due(BASE.replace(hour=12, minute=30).timestamp())
        self.assertEqual(second.data["schedules"], (expressions[2],))
        self.assertNotEqual(first.event_id, second.event_id)

    def test_starting_on_an_exact_boundary_does_not_fire_immediately(self):
        trigger = self.make()
        start = BASE.replace(hour=9)
        self.prime(trigger, start)
        self.assertIsNone(trigger._check_due(start.timestamp()))
        self.assertEqual(
            trigger._next_times["0 9 * * *"], (start + timedelta(days=1)).timestamp()
        )

    def test_delayed_wakeup_emits_only_latest_instant_with_all_matches(self):
        expressions = ("0 9 * * *", "0 12 * * *", "0 12 * * 1-5", "0 18 * * *")
        trigger = self.make(expressions)
        self.prime(trigger)
        now = BASE.replace(hour=17, minute=15, second=20).timestamp()
        message = trigger._check_due(now)
        self.assertEqual(message.timestamp, now)
        self.assertEqual(message.data["scheduled_at"], BASE.replace(hour=12))
        self.assertEqual(message.data["schedules"], expressions[1:3])
        self.assertIsNone(trigger._check_due(now))
        self.assertTrue(
            all(timestamp > now for timestamp in trigger._next_times.values())
        )

    def test_long_delay_skips_without_enumerating_each_elapsed_minute(self):
        trigger = self.make(("* * * * *", "0 9 * * *"))
        self.prime(trigger)
        now = BASE.replace(year=2036, hour=9, minute=0, second=0).timestamp()
        with patch.object(trigger, "_iterator", wraps=trigger._iterator) as iterator:
            message = trigger._check_due(now)
        self.assertEqual(message.data["scheduled_at"].timestamp(), now)
        self.assertEqual(message.data["schedules"], trigger.schedules)
        self.assertLessEqual(iterator.call_count, 4)

    def test_clock_rollback_does_not_replay_consumed_or_skipped_times(self):
        trigger = self.make(("0 9 * * *", "0 12 * * *", "0 18 * * *"))
        self.prime(trigger)
        message = trigger._check_due(BASE.replace(hour=18).timestamp())
        self.assertEqual(message.data["scheduled_at"].hour, 18)
        for hour in (8, 9, 12, 18):
            self.assertIsNone(trigger._check_due(BASE.replace(hour=hour).timestamp()))
        # A restart after a clock rollback also preserves the watermark.
        self.prime(trigger, BASE)
        self.assertIsNone(trigger._check_due(BASE.replace(hour=18).timestamp()))
        tomorrow = BASE.replace(hour=9) + timedelta(days=1)
        self.assertEqual(
            trigger._check_due(tomorrow.timestamp()).data["scheduled_at"], tomorrow
        )

    def test_day_or_controls_combined_day_and_weekday(self):
        # Nov 3 is Tuesday; next Monday is Nov 9, next day-of-month 3 is Dec 3.
        base = datetime(2026, 11, 3, 10, tzinfo=UTC)
        either = self.make("0 9 3 * mon", day_or=True)
        both = self.make("0 9 3 * mon", day_or=False)
        self.prime(either, base)
        self.prime(both, base)
        self.assertEqual(
            datetime.fromtimestamp(next(iter(either._next_times.values())), UTC),
            datetime(2026, 11, 9, 9, tzinfo=UTC),
        )
        result = datetime.fromtimestamp(next(iter(both._next_times.values())), UTC)
        self.assertEqual(result.day, 3)
        self.assertEqual(result.weekday(), 0)

    def test_calendar_lists_ranges_and_steps(self):
        trigger = self.make("*/15 9,12 * * 1-5")
        self.prime(trigger)
        for hour, minute in ((9, 0), (9, 15), (9, 30), (9, 45), (12, 0)):
            planned = BASE.replace(hour=hour, minute=minute)
            message = trigger._check_due(planned.timestamp())
            self.assertEqual(message.data["scheduled_at"], planned)

    def test_dst_repeated_local_time_represents_two_distinct_instants(self):
        zone = ZoneInfo("America/New_York")
        trigger = self.make("30 1 * * *", timezone=zone.key)
        self.prime(trigger, datetime(2026, 11, 1, tzinfo=zone))
        first = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
        second = first.replace(fold=1)
        one = trigger._check_due(first.timestamp())
        two = trigger._check_due(second.timestamp())
        self.assertEqual(one.data["scheduled_at"].timestamp(), first.timestamp())
        self.assertEqual(two.data["scheduled_at"].timestamp(), second.timestamp())
        self.assertEqual(two.data["scheduled_at"].fold, 1)
        self.assertNotEqual(one.event_id, two.event_id)

    def test_dst_spring_gap_uses_croniter_adjusted_occurrence(self):
        zone = ZoneInfo("America/New_York")
        trigger = self.make("30 2 * * *", timezone=zone.key)
        self.prime(trigger, datetime(2026, 3, 8, tzinfo=zone))
        adjusted = datetime(2026, 3, 8, 3, tzinfo=zone)
        message = trigger._check_due(adjusted.timestamp())
        self.assertEqual(message.data["scheduled_at"].timestamp(), adjusted.timestamp())
        self.assertEqual(
            datetime.fromtimestamp(next(iter(trigger._next_times.values())), zone),
            datetime(2026, 3, 9, 2, 30, tzinfo=zone),
        )

    def test_worker_checks_wall_clock_and_uses_shared_queue_policy(self):
        trigger = self.make(("0 9 * * *", "0 12 * * *"))
        self.prime(trigger)
        timestamps = [
            BASE.replace(hour=8, minute=59, second=59).timestamp(),
            BASE.replace(hour=9).timestamp(),
            BASE.replace(hour=8).timestamp(),
            BASE.replace(hour=12).timestamp(),
        ]
        with (
            patch.object(trigger, "get_timestamp", side_effect=timestamps),
            patch.object(
                trigger._stop_event, "wait", side_effect=[False, False, False, True]
            ) as wait,
        ):
            trigger.watching_loop()
        self.assertTrue(all(0 < call.args[0] <= 1 for call in wait.call_args_list))
        first = trigger._take_message()
        trigger._complete_message()
        second = trigger._take_message()
        trigger._complete_message()
        self.assertEqual(first.data["scheduled_at"].hour, 9)
        self.assertEqual(second.data["scheduled_at"].hour, 12)

    def test_queue_full_drops_new_occurrence_and_logs_warning(self):
        trigger = self.make("* * * * *", q_size=1)
        self.prime(trigger)
        with (
            patch.object(
                trigger,
                "get_timestamp",
                side_effect=[
                    BASE.timestamp() + 60,
                    BASE.timestamp() + 120,
                ],
            ),
            patch.object(trigger._stop_event, "wait", side_effect=[False, True]),
            self.assertLogs(MODULE, level="WARNING") as logs,
        ):
            trigger.watching_loop()
        self.assertEqual(len(logs.output), 1)
        self.assertEqual(len(trigger._message_queue), 1)
        self.assertEqual(trigger._cursor, BASE.timestamp() + 120)

    def test_stop_interrupts_distant_wait_and_restart_skips_stopped_period(self):
        trigger = self.make("0 9 * * *")
        with patch.object(trigger, "get_timestamp", return_value=BASE.timestamp()):
            trigger.start()
            original = trigger._watch_thread
            trigger.start()
            self.assertIs(trigger._watch_thread, original)
            trigger.stop()
        self.assertFalse(original.is_alive())
        self.assertTrue(trigger.is_stopped)
        original_id = trigger.id
        trigger._set_event(c.TriggerMessage(0, "stale"))
        trigger.stop()
        self.assertFalse(trigger.message_event.is_set())
        with patch.object(
            trigger, "get_timestamp", return_value=BASE.replace(hour=10).timestamp()
        ):
            trigger.start()
            self.assertNotEqual(trigger._watch_thread, original)
            self.assertFalse(trigger.message_event.is_set())
            self.assertEqual(
                next(iter(trigger._next_times.values())),
                (BASE.replace(hour=9) + timedelta(days=1)).timestamp(),
            )
            trigger.stop()
        self.assertEqual(trigger.id, original_id)

    def test_thread_start_failure_cleans_up_and_can_be_retried(self):
        trigger = self.make()
        with patch(f"{MODULE}.Thread") as thread:
            thread.return_value.start.side_effect = RuntimeError("cannot start")
            with self.assertRaisesRegex(RuntimeError, "cannot start"):
                trigger.start()
        self.assertIsNone(trigger._watch_thread)
        self.assertTrue(trigger.is_stopped)
        self.assertEqual(trigger._next_times, {})
        trigger.start()
        trigger.stop()

    def test_bad_options_do_not_register_a_component(self):
        baseline = Closure().objects
        for schedules, options, error in (
            ((), {}, ValueError),
            ("", {}, ValueError),
            (b"* * * * *", {}, TypeError),
            (None, {}, TypeError),
            ((1,), {}, TypeError),
            ("@daily", {}, ValueError),
            ("* * * * * *", {}, ValueError),
            ("* * * * * * 2027", {}, ValueError),
            ("60 0 * * *", {}, ValueError),
            ("0 0 30 2 *", {}, ValueError),
            ("R * * * *", {}, ValueError),
            ("H/5 * * * *", {}, ValueError),
            ("0 9 * * *", {"timezone": "No/Such_Zone"}, ValueError),
            ("0 9 * * *", {"timezone": ""}, ValueError),
            ("0 9 * * *", {"timezone": 123}, TypeError),
            ("0 9 * * *", {"day_or": 1}, TypeError),
            ("0 9 * * *", {"q_size": 0}, ValueError),
            ("0 9 * * *", {"callback": lambda event: None}, TypeError),
        ):
            with self.subTest(schedules=schedules, options=options):
                with self.assertRaises(error):
                    self.make(schedules, **options)
        self.assertEqual(Closure().objects, baseline)

    def test_flow_dispatches_event_and_stops_schedule_worker(self):
        clock = [BASE.timestamp()]
        ready, received_event = Event(), Event()
        received = []

        class ReadySchedule(c.ScheduleTrigger):
            def start(self):
                super().start()
                ready.set()

        class App(c.Dealer):
            def setup(self):
                self.schedule = ReadySchedule("0 9 * * *", self.tick, timezone="UTC")

            def tick(self, event: c.TriggerEvent):
                received.append((event, self.current_event))
                received_event.set()
                self.close()

        with patch.object(
            c.ScheduleTrigger, "get_timestamp", side_effect=lambda: clock[0]
        ):
            app = App()
            thread = Thread(target=app.start)
            thread.start()
            try:
                self.assertTrue(ready.wait(3))
                clock[0] = BASE.replace(hour=9).timestamp()
                self.assertTrue(received_event.wait(5))
            finally:
                app.close()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(received), 1)
        event, current = received[0]
        self.assertIs(event, current)
        self.assertIs(event.trigger, app.schedule)
        self.assertEqual(event.trigger_id, app.schedule.id)
        self.assertEqual(event.data["scheduled_at"], BASE.replace(hour=9))
        self.assertTrue(app.schedule.is_stopped)
        self.assertIsNone(app.schedule._watch_thread)


if __name__ == "__main__":
    unittest.main()
