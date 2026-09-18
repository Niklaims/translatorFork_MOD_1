"""
Регресс для находки группы ui_dialogs_setup_b (gemini_translator/ui/dialogs/setup.py):

- ui-dialogs-setup/logic/6-api-keys-persisted-in-project-: _get_full_ui_settings
  кладёт в снимок настроек 'api_keys' и 'active_keys_by_provider' — полные
  строки API-ключей открытым текстом. Этот снимок пишется в project_settings.json
  (_save_project_settings_only) и в таблицу meta_info файла queue_snapshot.db
  проекта (_write_snapshot_ui_settings) — оба файла лежат в пользовательской
  папке проекта, которую делятся/архивируют/кладут в облако.

Фикс: перед записью в файлы проекта секретные поля вырезаются
(_strip_secret_key_settings); при последующем восстановлении
(_apply_full_ui_settings) отсутствие 'api_keys' в применяемом снимке больше не
трактуется как «активных ключей нет» — активный набор не затирается, а
перечитывается из уже загруженного состояния (глобальные настройки/статусы
ключей) через key_management_widget._load_and_refresh_keys().
"""
import json
import os
import sqlite3
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gemini_translator.ui.dialogs import setup as setup_dialog
from gemini_translator.ui.dialogs.setup import InitialSetupPage

_SECRET_KEY = "AIzaSyREALSECRETVALUE1234567890abcd"


def _bare_page():
    """Голый экземпляр InitialSetupPage без __init__ — минимальный харнесс
    для вызова боевых методов, как в остальных test_fix_med_ui_dialogs_setup_*
    тестах."""
    return InitialSetupPage.__new__(InitialSetupPage)


# ---------------------------------------------------------------------------
# ui-dialogs-setup/logic/6-api-keys-persisted-in-project-
# ---------------------------------------------------------------------------

def test_write_snapshot_ui_settings_does_not_persist_api_keys(tmp_path):
    """Метаданные ui_session_settings в queue_snapshot.db не должны содержать
    полные API-ключи: файл лежит в папке проекта и может быть заархивирован
    или отдан кому-то вместе с книгой."""
    page = _bare_page()
    snapshot_path = str(tmp_path / "queue_snapshot.db")
    # Файл снапшота уже существует к моменту записи метаданных (создаётся
    # save_queue_snapshot до вызова _write_snapshot_ui_settings).
    sqlite3.connect(snapshot_path).close()

    settings = {
        "provider": "gemini",
        "num_instances": 3,
        "api_keys": [_SECRET_KEY],
        "active_keys_by_provider": {"gemini": [_SECRET_KEY]},
    }

    page._write_snapshot_ui_settings(snapshot_path, settings)

    conn = sqlite3.connect(snapshot_path)
    row = conn.execute(
        "SELECT value FROM meta_info WHERE key = 'ui_session_settings'"
    ).fetchone()
    conn.close()

    assert row is not None
    raw_payload = row[0]
    # РЕГРЕСС: до фикса секретный ключ попадал в payload открытым текстом.
    assert _SECRET_KEY not in raw_payload

    saved = json.loads(raw_payload)
    assert "api_keys" not in saved
    assert "active_keys_by_provider" not in saved
    # Остальные настройки по-прежнему сохраняются.
    assert saved["num_instances"] == 3
    assert saved["provider"] == "gemini"


def test_save_project_settings_only_does_not_persist_api_keys(tmp_path, monkeypatch):
    """project_settings.json (через SettingsManager.save_full_session_settings)
    не должен получать 'api_keys'/'active_keys_by_provider' — это боевой путь
    сохранения настроек проекта по кнопке/при выходе."""
    page = _bare_page()
    page.output_folder = str(tmp_path)
    page.is_settings_dirty = True
    page._refresh_dirty_window_title = lambda: None
    page._get_full_ui_settings = lambda: {
        "provider": "gemini",
        "num_instances": 2,
        "api_keys": [_SECRET_KEY],
        "active_keys_by_provider": {"gemini": [_SECRET_KEY]},
    }

    captured = {}

    class _FakeSettingsManager:
        def __init__(self, config_file=None):
            captured["config_file"] = config_file

        def save_full_session_settings(self, payload):
            captured["payload"] = dict(payload)
            return True

    monkeypatch.setattr(setup_dialog, "SettingsManager", _FakeSettingsManager)
    monkeypatch.setattr(
        setup_dialog.api_config, "custom_provider_models_snapshot", lambda: {}
    )
    monkeypatch.setattr(
        setup_dialog.api_config, "set_custom_provider_models", lambda _snap: None
    )

    page._save_project_settings_only()

    assert "payload" in captured
    payload = captured["payload"]
    # РЕГРЕСС: до фикса сюда попадали полные ключи открытым текстом.
    assert "api_keys" not in payload
    assert "active_keys_by_provider" not in payload
    assert payload["num_instances"] == 2
    assert page.is_settings_dirty is False


def test_apply_full_ui_settings_does_not_wipe_active_keys_when_absent():
    """Когда в применяемом снимке настроек нет 'api_keys' (например, он
    загружен из project_settings.json/queue_snapshot.db, где секретные поля
    намеренно вырезаны), уже загруженный активный набор ключей для провайдера
    не должен затираться пустым списком.

    Проверяем НАБЛЮДАЕМОЕ свойство (набор ключей провайдера не опустел), а не
    то, КАКИМ методом это достигнуто: восстановление провайдера снимка теперь
    обязано идти через set_active_keys_for_provider (см. соседний тест
    test_apply_full_ui_settings_restores_provider_when_api_keys_absent) — этот
    метод не должен получить на вход пустой список для уже известного набора."""
    page = _bare_page()
    page.model_settings_widget = MagicMock()
    page.translation_options_widget = MagicMock()
    page.preset_widget = MagicMock()
    page.instances_spin = MagicMock()
    page.auto_translate_widget = MagicMock()
    page.key_management_widget = MagicMock()
    page.key_management_widget.current_active_keys_by_provider = {"gemini": {_SECRET_KEY}}
    # Явно задаём эти три атрибута как объекты (а не полагаемся на hasattr
    # вернуть False) — на «голом» QObject-наследнике без super().__init__()
    # hasattr() для ОТСУТСТВУЮЩЕГО атрибута падает в sip с RuntimeError,
    # а не просто возвращает False.
    page.prevent_sleep_checkbox = MagicMock()
    page.queue_autosave_checkbox = MagicMock()
    page.show_chapter_chars_checkbox = MagicMock()

    page._update_instances_spinbox_limit = lambda: None
    page._refresh_auto_translate_runtime_context = lambda: None
    page._sync_chapter_char_display_settings = lambda: None
    page._update_distribution_info_from_widget = lambda: None
    page.check_ready = lambda: None

    # Имитируем ту часть реального set_active_keys_for_provider, которая
    # важна для инварианта (key_management_widget.py:694 — первая строка
    # метода: сохранить переданный набор в current_active_keys_by_provider).
    # Так тест ловит регресс независимо от того, вызывается ли метод вообще
    # или заменён на что-то другое — важен только конечный результат.
    def _fake_set_active_keys_for_provider(provider_id, active_keys):
        page.key_management_widget.current_active_keys_by_provider[provider_id] = set(
            active_keys
        )

    page.key_management_widget.set_active_keys_for_provider.side_effect = (
        _fake_set_active_keys_for_provider
    )

    settings = {"provider": "gemini"}  # 'api_keys' намеренно отсутствует

    page._apply_full_ui_settings(settings)

    # РЕГРЕСС: до фикса else-ветка звала set_active_keys_for_provider('gemini', [])
    # (в промежуточной версии) либо вообще не восстанавливала провайдер —
    # в обоих случаях набор ключей для gemini терялся/опустошался.
    assert page.key_management_widget.current_active_keys_by_provider.get("gemini")
    assert (
        _SECRET_KEY
        in page.key_management_widget.current_active_keys_by_provider["gemini"]
    )


def test_apply_full_ui_settings_restores_provider_when_api_keys_absent():
    """major-замечание ревью: заменённый вызов set_active_keys_for_provider
    делал больше, чем просто выставлял активный набор ключей — он ЕЩЁ
    переключал provider_combo на нужного провайдера (через _on_provider_changed,
    key_management_widget.py:694-709) и рассылал событие 'provider_changed'.
    Если применяемый снимок (например, из project_settings.json, где 'api_keys'
    вырезан) относится к провайдеру, ОТЛИЧНОМУ от того, что сейчас выбран в
    UI (глобально был gemini, в проекте — nvidia), провайдер проекта должен
    быть восстановлен — иначе model_settings_widget.set_settings не найдёт
    модель nvidia в списке моделей gemini и подставит чужую."""
    page = _bare_page()
    page.model_settings_widget = MagicMock()
    page.translation_options_widget = MagicMock()
    page.preset_widget = MagicMock()
    page.instances_spin = MagicMock()
    page.auto_translate_widget = MagicMock()
    page.key_management_widget = MagicMock()
    page.key_management_widget.current_active_keys_by_provider = {
        "gemini": {"gemini-key"},
        "nvidia": {"nvidia-key"},
    }
    page.prevent_sleep_checkbox = MagicMock()
    page.queue_autosave_checkbox = MagicMock()
    page.show_chapter_chars_checkbox = MagicMock()

    page._update_instances_spinbox_limit = lambda: None
    page._refresh_auto_translate_runtime_context = lambda: None
    page._sync_chapter_char_display_settings = lambda: None
    page._update_distribution_info_from_widget = lambda: None
    page.check_ready = lambda: None

    # Снимок пришёл из project_settings.json ('api_keys' вырезан), провайдер
    # проекта — nvidia, а в UI сейчас может быть выбран любой другой провайдер.
    settings = {"provider": "nvidia"}

    page._apply_full_ui_settings(settings)

    # РЕГРЕСС: до этого фикса else-ветка вызывала только
    # _load_and_refresh_keys(), который читает УЖЕ выбранный в UI провайдер
    # (self.get_selected_provider()) и никогда не переключает provider_combo —
    # выбор провайдера проекта (nvidia) терялся молча.
    page.key_management_widget.set_active_keys_for_provider.assert_called_once_with(
        "nvidia", ["nvidia-key"]
    )
    # Активный набор gemini, не относящийся к этому снимку, не тронут.
    assert page.key_management_widget.current_active_keys_by_provider["gemini"] == {
        "gemini-key"
    }


def test_apply_full_ui_settings_still_sets_active_keys_when_present():
    """Характеризация: если 'api_keys' явно присутствует в снимке (например,
    восстановление глобальной сессионной настройки), поведение не меняется —
    активный набор для провайдера по-прежнему выставляется явно."""
    page = _bare_page()
    page.model_settings_widget = MagicMock()
    page.translation_options_widget = MagicMock()
    page.preset_widget = MagicMock()
    page.instances_spin = MagicMock()
    page.auto_translate_widget = MagicMock()
    page.key_management_widget = MagicMock()
    page.key_management_widget.current_active_keys_by_provider = {}
    page.prevent_sleep_checkbox = MagicMock()
    page.queue_autosave_checkbox = MagicMock()
    page.show_chapter_chars_checkbox = MagicMock()

    page._update_instances_spinbox_limit = lambda: None
    page._refresh_auto_translate_runtime_context = lambda: None
    page._sync_chapter_char_display_settings = lambda: None
    page._update_distribution_info_from_widget = lambda: None
    page.check_ready = lambda: None

    settings = {"provider": "gemini", "api_keys": ["key-a", "key-b"]}

    page._apply_full_ui_settings(settings)

    page.key_management_widget.set_active_keys_for_provider.assert_called_once_with(
        "gemini", ["key-a", "key-b"]
    )
    page.key_management_widget._load_and_refresh_keys.assert_not_called()
