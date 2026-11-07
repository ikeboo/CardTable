import logging
import multiprocessing
import tempfile
import unittest
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from unittest.mock import patch

import cardtable as c
import cardtable._logging as logging_config
from cardtable.widgets._logging import LogListener, configure_ui_logging


def _emit_ui_logs(queue):
    configure_ui_logging(queue)
    logger = logging.getLogger("cardtable.test_ui")
    logger.debug("debug message")
    _UiSource().write(logger)
    try:
        raise ValueError("ui failure")
    except ValueError:
        logger.exception("ui exception")
    queue.close()
    queue.join_thread()


class _UiSource:
    def write(self, logger):
        logger.info("info message")


class LoggingTest(unittest.TestCase):
    def setUp(self):
        self.old_level = c.logger.level
        self.old_handler = logging_config._handler
        logging_config._handler = None

    def tearDown(self):
        handler = logging_config._handler
        if handler is not None:
            c.logger.removeHandler(handler)
            handler.close()
        logging_config._handler = self.old_handler
        c.logger.setLevel(self.old_level)

    def test_setup_writes_start_marker_for_each_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            c.set_logger(directory, level="INFO")
            c.set_logger(directory, level="INFO")
            path = next(Path(directory).glob("cardtable_*.log"))
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertTrue(all(line.endswith("started" + "-" * 50) for line in lines))
            logging_config._handler.close()

    def test_start_marker_respects_log_level(self):
        with tempfile.TemporaryDirectory() as directory:
            c.set_logger(directory, level="WARNING")
            path = next(Path(directory).glob("cardtable_*.log"))
            self.assertEqual(path.read_text(encoding="utf-8"), "")
            logging_config._handler.close()

    def test_public_logger_rotates_and_reconfiguration_replaces_handler(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first"
            second = Path(directory) / "second"
            with patch("cardtable._logging.datetime", wraps=datetime) as clock:
                clock.now.return_value = datetime(2026, 11, 2, 23, 59)
                c.set_logger(first, rotation="daily", level="warning", backup_count=2)
                c.logger.info("filtered")
                c.logger.warning("first message")
                clock.now.return_value = datetime(2026, 11, 3)
                c.logger.error("after rollover")
            c.set_logger(second, rotation="hourly", level="DEBUG")
            c.logger.debug("second directory")

            self.assertEqual(len(list(first.glob("cardtable_*.log"))), 2)
            rotated = (first / "cardtable_20261102.log").read_text()
            self.assertIn("first message", rotated)
            self.assertNotIn("filtered", rotated)
            current = (first / "cardtable_20261103.log").read_text()
            self.assertIn("after rollover", current)
            self.assertNotIn("second directory", current)
            self.assertIn("second directory", next(second.glob("cardtable_*.log")).read_text())
            self.assertEqual(logging_config._handler.rotation, "hourly")
            logging_config._handler.close()

    def test_hourly_and_weekly_names_and_retention(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("cardtable._logging.datetime", wraps=datetime) as clock:
                clock.now.return_value = datetime(2026, 11, 2, 9, 59)
                c.set_logger(directory, rotation="hourly", backup_count=1)
                c.logger.info("nine")
                clock.now.return_value = datetime(2026, 11, 2, 10)
                c.logger.info("ten")
                clock.now.return_value = datetime(2026, 11, 2, 11)
                c.logger.info("eleven")
                self.assertEqual(
                    sorted(p.name for p in Path(directory).glob("*.log")),
                    ["cardtable_2026110210.log", "cardtable_2026110211.log"],
                )
                clock.now.return_value = datetime(2026, 11, 4)
                c.set_logger(directory, rotation="weekly")
                c.logger.info("this week")
                clock.now.return_value = datetime(2026, 11, 9)
                c.logger.info("next week")
                self.assertTrue((Path(directory) / "cardtable_20261102.log").exists())
                self.assertTrue((Path(directory) / "cardtable_20261109.log").exists())
                logging_config._handler.close()

    def test_invalid_configuration_preserves_existing_handler(self):
        with tempfile.TemporaryDirectory() as directory:
            c.set_logger(directory)
            old_handler = logging_config._handler
            with self.assertRaises(ValueError):
                c.set_logger(directory, rotation="yearly")
            with self.assertRaises(ValueError):
                c.set_logger(directory, level="unknown")
            self.assertIs(logging_config._handler, old_handler)
            old_handler.close()

    def test_public_configuration_receives_spawned_ui_logs(self):
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        listener = LogListener(queue)
        with tempfile.TemporaryDirectory() as directory:
            c.set_logger(directory, level="INFO")
            listener.start()
            process = context.Process(
                target=_emit_ui_logs, args=(queue,), name="cardtable-ui"
            )
            try:
                process.start()
                process.join(10)
                self.assertEqual(process.exitcode, 0)
            finally:
                if process.is_alive():
                    process.terminate()
                    process.join()
                listener.stop()
                queue.close()
                queue.join_thread()
            contents = next(Path(directory).glob("cardtable_*.log")).read_text()
            self.assertNotIn("debug message", contents)
            self.assertIn("info message", contents)
            self.assertIn("_UiSource.write", contents)
            self.assertIn("test_logging._emit_ui_logs", contents)
            self.assertIn(f"UI_PID:{process.pid}", contents)
            self.assertIn("ValueError: ui failure", contents)
            logging_config._handler.close()

    def test_fixed_columns_and_caller_for_methods_and_functions(self):
        with tempfile.TemporaryDirectory() as directory:
            c.set_logger(directory, level="DEBUG")

            class Example:
                def short(self):
                    c.logger.info("first")

                @staticmethod
                def static():
                    c.logger.warning("second")

            Example().short()
            Example.static()
            c.logger.debug("third")
            lines = (
                next(Path(directory).glob("cardtable_*.log")).read_text().splitlines()
            )
            lines = [line for line in lines if not line.endswith("started" + "-" * 50)]
            self.assertEqual(len(lines), 3)
            separators = [[i for i, char in enumerate(line) if char == "|"]
                          for line in lines]
            self.assertEqual(separators, [[20, 31, 54, 97]] * 3)
            self.assertIn(
                f"Main_PID:{multiprocessing.current_process().pid}", lines[0]
            )
            self.assertIn("Example.short", lines[0])
            self.assertIn("Example.static", lines[1])
            self.assertIn("LoggingTest.test_fixed_columns", lines[2])
            logging_config._handler.close()

    def test_long_names_are_truncated_to_column_width(self):
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello", (), None)
        record.processName = "p" * 30
        record.cardtable_caller = "Caller." + "m" * 50
        formatter = logging_config._LogFormatter(
            "%(levelname)s | %(processName)s | %(cardtable_caller)s | %(message)s"
        )
        parts = formatter.format(record).split(" | ")
        self.assertEqual([len(part) for part in parts[:3]], [8, 20, 40])
        self.assertIn("..._PID:", parts[1])
        self.assertTrue(parts[1].rstrip().endswith(str(record.process)))
        self.assertTrue(parts[2].endswith("..."))

    def test_spawned_ui_logs_follow_parent_configuration(self):
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        listener = LogListener(queue)
        logger = logging.getLogger("cardtable.test_ui")
        previous_level, previous_propagate = logger.level, logger.propagate
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.log"
            handler = TimedRotatingFileHandler(path, when="midnight", encoding="utf-8")
            handler.setLevel(logging.INFO)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.propagate = False
            listener.start()
            process = context.Process(target=_emit_ui_logs, args=(queue,))
            try:
                process.start()
                process.join(10)
                self.assertEqual(process.exitcode, 0)
            finally:
                if process.is_alive():
                    process.terminate()
                    process.join()
                listener.stop()
                queue.close()
                queue.join_thread()
                logger.removeHandler(handler)
                logger.setLevel(previous_level)
                logger.propagate = previous_propagate
                handler.close()
            contents = path.read_text(encoding="utf-8")
            self.assertNotIn("debug message", contents)
            self.assertIn("info message", contents)
            self.assertIn("ui exception", contents)
            self.assertIn("ValueError: ui failure", contents)
