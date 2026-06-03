import logging
import sys
import unittest

from utils.log_bus import QtLogHandler


class _FakeSignal:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _FakeBus:
    def __init__(self):
        self.record_emitted = _FakeSignal()


class TestQtLogHandler(unittest.TestCase):
    def test_emit_includes_traceback_without_custom_formatter(self):
        bus = _FakeBus()
        handler = QtLogHandler(bus)

        try:
            raise RuntimeError("boom")
        except RuntimeError:
            record = logging.LogRecord(
                "demo",
                logging.ERROR,
                "demo.py",
                12,
                "failed %s",
                ("run",),
                sys.exc_info(),
            )

        handler.emit(record)

        self.assertEqual(len(bus.record_emitted.calls), 1)
        _, logger_name, message, _ = bus.record_emitted.calls[0]
        self.assertEqual(logger_name, "demo")
        self.assertIn("failed run", message)
        self.assertIn("Traceback", message)
        self.assertIn("RuntimeError: boom", message)


if __name__ == "__main__":
    unittest.main()
