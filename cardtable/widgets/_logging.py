"""Forward UI-process log records to the application's logging configuration."""

import logging
from logging.handlers import QueueHandler, QueueListener

from cardtable._logging import _CallerFilter

from ._ui_process import run_ui_process


class LogListener(QueueListener):
    def handle(self, record):
        logger = logging.getLogger(record.name)
        if logger.isEnabledFor(record.levelno):
            logger.handle(record)


def configure_ui_logging(log_queue):
    # Spawn may import application code which configures logging. Remove those
    # handlers in this process: only the parent should write to its log files.
    root = logging.getLogger()
    for logger in [root, *logging.root.manager.loggerDict.values()]:
        if isinstance(logger, logging.Logger):
            # multiprocessing.Queue can itself log while enqueueing a record.
            if logger.name == "multiprocessing":
                logger.propagate = False
                continue
            logger.handlers.clear()
            logger.disabled = False
            if logger is not root:
                logger.setLevel(logging.NOTSET)
                logger.propagate = True
    logging.disable(logging.NOTSET)
    root.setLevel(logging.DEBUG)
    handler = QueueHandler(log_queue)
    handler.addFilter(_CallerFilter())
    root.addHandler(handler)


def run_ui_with_logging(log_queue, *args):
    configure_ui_logging(log_queue)
    root = logging.getLogger()
    try:
        run_ui_process(*args)
    finally:
        root.handlers.clear()
        log_queue.close()
        log_queue.join_thread()
