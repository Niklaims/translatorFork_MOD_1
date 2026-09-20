"""Перехватчик сообщений Qt не должен повторять отчёт SHERLOCK.

Ошибка Qt о работе с потоками, пойманная уже внутри патча
``_patched_qmessagebox_critical``, означает, что окно с ошибкой само сейчас
и строится. Второй разбор стека в этот момент — шум поверх уже идущего
отчёта, поэтому обработчик обязан промолчать.
"""

import contextlib
import io
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QtMsgType

import os_patch


THREADING_WARNING = (
    "QObject::killTimer: Timers cannot be stopped from another thread"
)


def _installed_handler():
    """Достаёт обработчик, который ``_install_qt_message_handler`` ставит в Qt."""
    captured = []
    with mock.patch(
        "PyQt6.QtCore.qInstallMessageHandler",
        side_effect=lambda handler: captured.append(handler),
    ):
        os_patch._install_qt_message_handler()
    assert captured, "обработчик так и не был установлен"
    return captured[-1]


def _run_handler(handler, message=THREADING_WARNING):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(io.StringIO()):
        handler(QtMsgType.QtWarningMsg, None, message)
    return buffer.getvalue()


class QtMessageHandlerRecursionTests(unittest.TestCase):
    def test_reports_threading_error_from_ordinary_frame(self):
        output = _run_handler(_installed_handler())
        self.assertIn("SHERLOCK", output)

    def test_stays_silent_inside_patched_message_box(self):
        handler = _installed_handler()

        # Имя кадра — единственный признак, по которому обработчик узнаёт,
        # что окно с ошибкой уже строится.
        def _patched_qmessagebox_critical():
            return _run_handler(handler)

        output = _patched_qmessagebox_critical()
        self.assertNotIn("SHERLOCK", output)

    def test_does_not_dump_stack_to_stderr_before_deciding(self):
        handler = _installed_handler()
        stderr = io.StringIO()

        def _patched_qmessagebox_critical():
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(stderr):
                handler(QtMsgType.QtWarningMsg, None, THREADING_WARNING)

        _patched_qmessagebox_critical()
        self.assertEqual("", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
