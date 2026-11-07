import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from cardtable.widgets._process_usage import ProcessUsage, _read_process


class ProcessUsageTest(unittest.TestCase):
    def test_real_ui_process_restarts_and_exits_with_usage_timer_active(self):
        script = textwrap.dedent("""
            import multiprocessing
            import time
            from queue import Empty
            from cardtable.widgets._ui_process import run_ui_process

            if __name__ == '__main__':
                context = multiprocessing.get_context('spawn')
                for cycle in range(3):
                    commands, events = context.Queue(), context.Queue()
                    ready = context.Event()
                    process = context.Process(
                        target=run_ui_process, args=(commands, events, ready)
                    )
                    try:
                        process.start()
                        assert ready.wait(5), 'UI startup timed out'
                        time.sleep(1.15)  # Allow the real one-second timer to run.
                        commands.put({'type': 'shutdown'})
                        process.join(3)
                        assert not process.is_alive(), 'UI shutdown timed out'
                        assert process.exitcode == 0, process.exitcode
                        while True:
                            try:
                                event = events.get_nowait()
                            except Empty:
                                break
                            assert 'error' not in event['type'], event
                    finally:
                        if process.is_alive():
                            process.terminate()
                            process.join(1)
                        for queue in (commands, events):
                            queue.cancel_join_thread()
                            queue.close()
        """)
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("invalid command name", result.stderr)
        self.assertNotIn("Exception in Tkinter callback", result.stderr)

    def test_interval_cpu_and_current_memory_are_summed(self):
        usage = ProcessUsage()
        usage._pids = {10, 20}
        with (
            patch("cardtable.widgets._process_usage.monotonic", side_effect=[5, 7]),
            patch("cardtable.widgets._process_usage._read_process") as read,
        ):
            read.side_effect = lambda pid: (pid, 600_000_000)
            self.assertEqual(usage.sample(), "CPU:0%, Mem.:1.20GB")
            read.side_effect = lambda pid: (pid + 0.5, 400_000_000)
            self.assertEqual(usage.sample(), "CPU:50%, Mem.:0.80GB")

    def test_failed_read_is_unavailable_and_resets_baseline(self):
        usage = ProcessUsage()
        with patch("cardtable.widgets._process_usage._read_process") as read:
            read.return_value = (1, 100_000_000)
            usage.sample()
            read.side_effect = OSError("process unavailable")
            self.assertEqual(usage.sample(), "CPU:--%, Mem.:--GB")
            read.side_effect = None
            read.return_value = (100, 100_000_000)
            self.assertTrue(usage.sample().startswith("CPU:0%"))

    def test_linux_process_name_can_contain_spaces_and_parentheses(self):
        fields = ["0"] * 22
        fields[11], fields[12], fields[21] = "120", "30", "200"
        with (
            patch("cardtable.widgets._process_usage.sys.platform", "linux"),
            patch(
                "pathlib.Path.read_text",
                return_value="10 (a ) name) " + " ".join(fields),
            ),
            patch("os.sysconf", side_effect=[100, 4096]),
        ):
            self.assertEqual(_read_process(10), (1.5, 819200))
