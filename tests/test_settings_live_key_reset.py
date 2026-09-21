import os
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

from gemini_translator.api import config as api_config
from gemini_translator.utils import settings as settings_module
from gemini_translator.utils.settings import SettingsManager


class _RecordingBus(QtCore.QObject):
    event_posted = QtCore.pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.events = []
        self.event_posted.connect(self.events.append)


class SettingsLiveKeyResetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        api_config.initialize_configs()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def _create_manager(self, bus):
        manager = SettingsManager(
            event_bus=bus,
            config_file=os.path.join(self.temp_dir.name, "settings.json"),
        )
        # Менеджер переживает тест (его держит подписка на aboutToQuit), а
        # таймер обслуживания лимитов тикает раз в 5 с и после удаления
        # временного каталога: хранилище квот пересоздаёт пустую базу и падает
        # с «no such table» внутри чужого теста, который крутит цикл событий.
        self.addCleanup(manager._limit_maintenance_timer.stop)
        # Хранилище квот держит соединение с базой открытым, а Windows не даёт
        # удалить временный каталог с открытым файлом.
        self.addCleanup(manager._key_runtime_store.close)
        return manager

    def test_expired_gemini_key_is_reset_and_announced_without_reload(self):
        bus = _RecordingBus()
        manager = self._create_manager(bus)

        expired_at = int(time.time()) - (48 * 60 * 60)
        manager.save_key_statuses([{"key": "GEMINI_TEST_KEY", "provider": "gemini"}])
        # save_key_statuses пишет только конфигурацию; runtime живёт в SQLite.
        manager._key_runtime_store.merge_statuses({
            "GEMINI_TEST_KEY": {
                "gemini-test-model": {
                    "exhausted_at": expired_at,
                    "exhausted_level": 2,
                    "requests": [expired_at],
                }
            }
        })

        bus.events.clear()
        manager._refresh_expired_key_limits()

        key_info = manager.get_key_info("GEMINI_TEST_KEY")
        model_status = key_info["status_by_model"]["gemini-test-model"]
        self.assertIsNone(model_status["exhausted_at"])
        self.assertEqual(model_status["exhausted_level"], 0)
        self.assertEqual(manager.get_request_count(key_info, "gemini-test-model"), 0)
        self.assertTrue(
            any(
                event.get("event") == "key_statuses_updated"
                and event.get("data", {}).get("reason") == "automatic_limit_reset"
                for event in bus.events
            )
        )

    def test_limit_maintenance_timer_runs_while_application_is_open(self):
        manager = self._create_manager(_RecordingBus())
        timer = manager._limit_maintenance_timer

        self.assertTrue(timer.isActive())
        self.assertTrue(timer.isSingleShot())
        self.assertLessEqual(timer.interval(), settings_module.LIMIT_MAINTENANCE_MAX_DELAY_S * 1000)

    def _maintained_pairs(self, manager):
        store = manager._key_runtime_store
        original = store.maintain_models
        sent = []

        def spy(items):
            items = list(items)
            sent.extend(items)
            return original(items)

        store.maintain_models = spy
        return sent

    def test_maintenance_touches_only_pairs_with_something_to_do(self):
        # Каждая пара — отдельный запрос к SQLite, и каждый отпускает GIL: при
        # 144 ключах 1368 пустых DELETE давали подвисание интерфейса, пока
        # перевод или анализ держит интерпретатор.
        manager = self._create_manager(_RecordingBus())
        now = int(time.time())
        old = now - 48 * 60 * 60
        manager.save_key_statuses([
            {"key": key, "provider": "gemini"}
            for key in ("OLD_REQUEST", "FRESH_REQUEST", "IDLE", "EXPIRED_LIMIT")
        ])
        manager._key_runtime_store.merge_statuses({
            "OLD_REQUEST": {"m": {"exhausted_at": None, "exhausted_level": 0, "requests": [old]}},
            "FRESH_REQUEST": {"m": {"exhausted_at": None, "exhausted_level": 0, "requests": [now]}},
            "IDLE": {"m": {"exhausted_at": None, "exhausted_level": 0, "requests": []}},
            "EXPIRED_LIMIT": {"m": {"exhausted_at": old, "exhausted_level": 2, "requests": []}},
        })
        sent = self._maintained_pairs(manager)

        manager._refresh_expired_key_limits()

        self.assertEqual(sorted(item[0] for item in sent), ["EXPIRED_LIMIT", "OLD_REQUEST"])

    def _rolling_manager(self, statuses):
        manager = self._create_manager(_RecordingBus())
        manager.save_key_statuses([{"key": "ROLLING_KEY", "provider": "nvidia"}])
        manager._key_runtime_store.merge_statuses({"ROLLING_KEY": {"m": statuses}})
        return manager

    def test_timer_sleeps_until_a_request_leaves_the_rolling_window(self):
        day = 24 * 60 * 60
        manager = self._rolling_manager({
            "exhausted_at": None, "exhausted_level": 0,
            "requests": [int(time.time()) - day + 300],
        })

        manager._refresh_expired_key_limits()

        interval_s = manager._limit_maintenance_timer.interval() / 1000
        self.assertGreater(interval_s, 280)
        self.assertLessEqual(interval_s, 301)

    def test_timer_sleeps_until_a_rolling_limit_expires(self):
        day = 24 * 60 * 60
        manager = self._rolling_manager({
            "exhausted_at": int(time.time()) - day + 200, "exhausted_level": 2, "requests": [],
        })

        manager._refresh_expired_key_limits()

        interval_s = manager._limit_maintenance_timer.interval() / 1000
        self.assertGreater(interval_s, 180)
        self.assertLessEqual(interval_s, 201)

    def test_timer_never_sleeps_longer_than_the_cap(self):
        # Gemini сбрасывает квоту раз в сутки, но на macOS таймер не идёт, пока
        # компьютер спит: без предела сброс в полночь заметили бы через много
        # часов после пробуждения.
        manager = self._create_manager(_RecordingBus())
        manager.save_key_statuses([{"key": "GEMINI_KEY", "provider": "gemini"}])
        manager._key_runtime_store.merge_statuses({
            "GEMINI_KEY": {"m": {"exhausted_at": int(time.time()), "exhausted_level": 2, "requests": []}},
        })

        manager._refresh_expired_key_limits()

        self.assertLessEqual(
            manager._limit_maintenance_timer.interval(),
            settings_module.LIMIT_MAINTENANCE_MAX_DELAY_S * 1000,
        )
        self.assertGreaterEqual(
            manager._limit_maintenance_timer.interval(),
            settings_module.LIMIT_MAINTENANCE_MIN_DELAY_S * 1000,
        )

    def test_loading_keys_keeps_current_limit_and_resets_an_expired_one(self):
        manager = self._create_manager(_RecordingBus())
        now = int(time.time())
        expired_at = now - (48 * 60 * 60)
        manager.save_key_statuses([
            {"key": "CURRENTLY_LIMITED_KEY", "provider": "gemini"},
            {"key": "EXPIRED_KEY", "provider": "gemini"},
        ])
        # save_key_statuses пишет только конфигурацию; runtime живёт в SQLite.
        manager._key_runtime_store.merge_statuses({
            "CURRENTLY_LIMITED_KEY": {
                "gemini-test-model": {
                    "exhausted_at": now,
                    "exhausted_level": 2,
                    "requests": [now],
                }
            },
            "EXPIRED_KEY": {
                "gemini-test-model": {
                    "exhausted_at": expired_at,
                    "exhausted_level": 2,
                    "requests": [expired_at],
                }
            },
        })

        statuses = {
            item["key"]: item for item in manager.load_key_statuses()
        }

        self.assertTrue(
            manager.is_key_limit_active(
                statuses["CURRENTLY_LIMITED_KEY"], "gemini-test-model"
            )
        )
        expired_status = statuses["EXPIRED_KEY"]["status_by_model"][
            "gemini-test-model"
        ]
        self.assertIsNone(expired_status["exhausted_at"])
        self.assertEqual(expired_status["exhausted_level"], 0)
        self.assertEqual(expired_status["requests"], [])


if __name__ == "__main__":
    unittest.main()
