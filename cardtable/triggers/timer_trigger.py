"""指定した時間間隔でトリガーを発火させるトリガー。

``TimerTrigger(5)`` は、5ミリ秒ごとにトリガーを発火させる。
"""

from threading import Thread, current_thread
from time import perf_counter_ns
from typing import Optional

from cardtable.core.trigger_callback import TriggerCallback
from cardtable.data_classes.trigger_message import TriggerMessage

from ._trigger import Trigger


class TimerTrigger(Trigger):
    """指定したミリ秒間隔でイベントを発火させるトリガー。

    Args:
        interval_ms: イベントを発火させる間隔（ミリ秒）。
        callback: 発火時にFlowが実行するコールバック。
    """

    def __init__(
        self,
        interval_ms: float,
        callback: TriggerCallback | None = None,
        *,
        drop_if_busy: bool = True,
        q_size: int = 10,
        log_level: str | int = "DEBUG",
    ):
        if isinstance(interval_ms, bool) or not isinstance(interval_ms, (int, float)):
            raise TypeError("interval_ms must be a number")
        if interval_ms <= 0:
            raise ValueError("interval_ms must be greater than zero")

        super().__init__(
            callback=callback,
            drop_if_busy=drop_if_busy,
            q_size=q_size,
            log_level=log_level,
        )
        self.interval_ms = interval_ms
        self._watch_thread: Optional[Thread] = None

    def start(self):
        """タイマーの監視を開始する。"""
        if self._watch_thread is not None and self._watch_thread.is_alive():
            return

        self._stop_event.clear()
        self.is_stopped = False
        self._watch_thread = Thread(target=self.watching_loop, daemon=True)
        self._watch_thread.start()

    def watching_loop(self):
        """停止されるまで、指定された間隔でイベントを発火させる。"""
        interval_ns = max(1, round(self.interval_ms * 1_000_000))
        next_fire_ns = perf_counter_ns() + interval_ns

        while True:
            # 前回の発火からではなく、開始時刻を基準に待つ。これにより
            # メッセージ生成・通知にかかった時間が周期ごとに累積しない。
            remaining_ns = max(0, next_fire_ns - perf_counter_ns())
            if self._stop_event.wait(remaining_ns / 1_000_000_000):
                break

            message = TriggerMessage(
                timestamp=self.get_timestamp(),
                data={"interval_ms": self.interval_ms},
            )
            self._set_event(message)

            # 処理が一周期以上遅れた場合、過去のイベントを連続発火せず、
            # 次の周期境界まで進める。
            now_ns = perf_counter_ns()
            elapsed_intervals = max(1, (now_ns - next_fire_ns) // interval_ns + 1)
            next_fire_ns += elapsed_intervals * interval_ns

    def stop(self):
        """タイマーの監視を停止し、監視スレッドを終了する。"""
        self._stop_event.set()

        watch_thread = self._watch_thread
        if (
            watch_thread is not None
            and watch_thread.is_alive()
            and watch_thread is not current_thread()
        ):
            watch_thread.join(timeout=1.0)

        self.is_stopped = True
