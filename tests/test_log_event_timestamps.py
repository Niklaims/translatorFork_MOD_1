import os
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from gemini_translator.ui.widgets.log_widget import CATCHUP_FLUSH_BATCH_SIZE, LogWidget
from main import EventBus


class LogEventTimestampTests(unittest.TestCase):
    """Строка лога должна показывать время события, а не время отрисовки."""

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_render_uses_event_time_not_render_time(self):
        widget = LogWidget(event_bus=None)
        self.addCleanup(widget.close)

        event_time = time.time() - 3600  # событие произошло час назад
        html = widget._build_log_html(
            {"message": "[INFO] час назад", "timestamp": event_time}
        )

        self.assertIn(time.strftime("%H:%M:%S", time.localtime(event_time)), html)
        self.assertNotIn(time.strftime("%H:%M:%S", time.localtime()), html)

    def test_render_falls_back_to_now_without_timestamp(self):
        widget = LogWidget(event_bus=None)
        self.addCleanup(widget.close)

        html = widget._build_log_html({"message": "[INFO] без метки"})

        self.assertIn(time.strftime("%H:%M:%S", time.localtime()), html)

    def test_hidden_widget_keeps_arrival_time_for_whole_backlog(self):
        # Пользователь ушёл со вкладки: сообщения копятся, а рисуются позже.
        # Каждая строка обязана сохранить своё собственное время прихода.
        widget = LogWidget(event_bus=None)
        self.addCleanup(widget.close)
        self.assertFalse(widget.isVisible())

        arrival_times = [time.time() - 600 + index for index in range(3)]
        for index, arrival in enumerate(arrival_times):
            with mock.patch("time.time", return_value=arrival):
                widget.append_message({"message": f"[INFO] пункт {index}"})

        self.assertEqual(
            [data["timestamp"] for data in widget._pending_log_data],
            arrival_times,
        )

        widget._flush_pending_messages()
        rendered = widget.log_view.toPlainText()
        for arrival in arrival_times:
            self.assertIn(time.strftime("%H:%M:%S", time.localtime(arrival)), rendered)

    def test_overflow_notice_carries_its_own_time(self):
        widget = LogWidget(event_bus=None)
        self.addCleanup(widget.close)

        with mock.patch(
            "gemini_translator.ui.widgets.log_widget.MAX_PENDING_LOG_MESSAGES", 3
        ):
            for index in range(5):
                widget._queue_log_message({"message": f"[INFO] пункт {index}"})

        self.assertTrue(
            all("timestamp" in data for data in widget._pending_log_data),
            widget._pending_log_data,
        )

    def test_bus_stamps_log_events_when_they_happen(self):
        bus = EventBus()
        self.addCleanup(bus.deleteLater)

        before = time.time()
        event = {"event": "log_message", "source": "worker_1", "data": {"message": "[INFO] раз"}}
        bus.emit_event(event)
        after = time.time()

        stamped = event["data"].get("timestamp")
        self.assertIsNotNone(stamped)
        self.assertGreaterEqual(stamped, before)
        self.assertLessEqual(stamped, after)

    def test_bus_keeps_timestamp_set_by_producer(self):
        bus = EventBus()
        self.addCleanup(bus.deleteLater)

        event = {"event": "log_message", "data": {"message": "[INFO] два", "timestamp": 1234.5}}
        bus.emit_event(event)

        self.assertEqual(event["data"]["timestamp"], 1234.5)

    def test_widget_does_not_overwrite_timestamp_from_bus(self):
        widget = LogWidget(event_bus=None)
        self.addCleanup(widget.close)

        widget.append_message({"message": "[INFO] три", "timestamp": 1234.5})

        self.assertEqual(widget._pending_log_data[0]["timestamp"], 1234.5)

    def test_catchup_batch_size_is_still_the_smooth_chunk(self):
        # Метка времени не должна менять поведение плавного догона.
        self.assertGreater(CATCHUP_FLUSH_BATCH_SIZE, 0)


if __name__ == "__main__":
    unittest.main()
