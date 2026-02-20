"""
Loglama sistemi - dosya ve konsol çıktısı
"""

import logging
import sys
import os
from config import LOG_LEVEL, LOG_FILE, LOG_FORMAT


class FlushStreamHandler(logging.StreamHandler):
    """Her mesajdan sonra flush yap."""
    def emit(self, record):
        super().emit(record)
        self.flush()


class FlushFileHandler(logging.FileHandler):
    """Her mesajdan sonra flush yap."""
    def emit(self, record):
        super().emit(record)
        self.flush()


def setup_logger(name: str) -> logging.Logger:
    """Logger oluştur ve yapılandır."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    if not logger.handlers:
        # Konsol handler (stdout, flush her mesajda)
        console_handler = FlushStreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_fmt = logging.Formatter(LOG_FORMAT)
        console_handler.setFormatter(console_fmt)
        logger.addHandler(console_handler)

        # Dosya handler (flush her mesajda)
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        file_handler = FlushFileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(console_fmt)
        logger.addHandler(file_handler)

    return logger
