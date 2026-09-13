"""Регресс для ui-dialogs-validation/runtime/13-manual-qa-coordinator-stale.

_quality_coordinator раньше возвращало уже существующий app.qa_coordinator
без единой проверки, собран ли он с теми ключами/моделью/прокси, что настроены
сейчас. Пользователь мог поменять модель проверки или ключи в настройках,
открыть «Качество перевода» заново — и получить старый ручной координатор,
собранный ДО изменения.

Ревью нашло два дефекта в первой версии этого фикса, и тесты ниже покрывают
их отдельно от базового поведения:

* Отпечаток настроек был построен на green_keys() — а это здоровье КВОТЫ
  ключа (is_key_limit_active), не решение пользователя. Единственный ключ,
  поймавший дневной лимит посреди многочасового прохода, менял отпечаток
  без единого действия человека и валил живой координатор через
  detach_chapter_qa_coordinator -> shutdown() (blocker).
* Старый координатор отсоединялся ДО того, как выяснялось, удастся ли
  собрать новый. Если сборка проваливалась (например, у новой модели прямо
  сейчас нет ни одного зелёного ключа), рабочий runtime уже был уничтожен, а
  взамен не появлялось ничего — ровно тот момент, когда пользователь жмёт
  «Остановить» (major).

Тест проверяет через настоящий метод _quality_coordinator (только
qa.assembly/qa.handler_factory подменены, чтобы не поднимать реальный
QA-поток):
1. Пока настройки не менялись — координатор не пересобирается (тот же объект).
2. Если настройки ручной проверки изменились — старый координатор отсоединяется
   (detach_chapter_qa_coordinator) и собирается новый.
3. Координатор АКТИВНОЙ СЕССИИ ПЕРЕВОДА (не наш, ручной) никогда не трогается —
   это чужой координатор с других правилами жизненного цикла.
4. Смена ЗДОРОВЬЯ ключа (не самих настроенных ключей) не пересобирает координатор.
5. Пересборка откладывается, пока идёт проход, и происходит сразу после его конца.
6. Неудачная попытка пересобрать координатор не должна лишать окно рабочего.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication

from gemini_translator.ui.dialogs.validation import TranslationValidatorPage


class _FakeSettingsManager:
    """Полностью управляемый заменитель settings_manager для этого теста."""

    def __init__(self, provider, model, keys, proxy=None):
        self.provider = provider
        self.model = model
        # Ключи, которые НАСТРОЕНЫ у провайдера (то, что видит load_key_statuses
        # и, соответственно, отпечаток настроек) — меняются только явным
        # действием пользователя в этом тесте.
        self.keys = list(keys)
        # Ключи, которые сейчас «зелёные» по квоте (то, что видит green_keys()
        # при реальной сборке координатора). По умолчанию совпадает с keys, но
        # тест может развести их, чтобы отдельно эмулировать «ключ поймал
        # лимит», не трогая сами настройки.
        self.healthy_keys = list(keys)
        self.proxy = dict(proxy or {})
        # Один и тот же объект на все вызовы — как настоящий QaSettings с
        # неизменными полями сравнивается по значению, а не только по adresu.
        self._qa_settings = object()

    def get_qa_settings(self):
        return self._qa_settings

    def load_proxy_settings(self):
        return dict(self.proxy)

    def load_key_statuses(self):
        # Все НАСТРОЕННЫЕ ключи провайдера — то, что реально видно в
        # настройках, а не то, что сейчас "зелёное" по квоте.
        return [{"provider": self.provider, "key": key} for key in self.keys]


class _ProjectManagerStub:
    project_folder = "/tmp/project"


def _quiesce_page(page):
    """Гасит отложенную работу, которую конструктор страницы ставит на таймер.

    TranslationValidatorPage.__init__ запускает одноразовый QTimer (150 мс) на
    _populate_initial_table; в тесте страница живёт без реального проекта, и
    таймер сработал бы уже в чужом тесте того же процесса, уронив его
    исключением из Qt-слота (pytest-qt ловит их на любом тесте).
    """
    timer = getattr(page, "_populate_initial_table_timer", None)
    if timer is not None:
        timer.stop()


def _dispose_page(page):
    """deleteLater + доставка DeferredDelete: без этого QObject доживает до
    следующего оборота цикла событий уже в чужом тесте."""
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _make_page():
    with patch.object(TranslationValidatorPage, "_perform_initial_cjk_scan"):
        page = TranslationValidatorPage(
            "/tmp/nonexistent-translations",
            "/tmp/nonexistent-book.epub",
            project_manager=_ProjectManagerStub(),
        )
    _quiesce_page(page)
    return page


class StaleManualCoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.global_version = ""

    def setUp(self):
        # Один и тот же тестовый прогон не должен видеть чужой qa_coordinator,
        # оставшийся от другого теста этого же процесса.
        self._had_coordinator = hasattr(self.app, "qa_coordinator")
        self._previous_coordinator = getattr(self.app, "qa_coordinator", None)
        self.app.qa_coordinator = None
        self.addCleanup(self._restore_app_coordinator)

    def _restore_app_coordinator(self):
        if self._had_coordinator:
            self.app.qa_coordinator = self._previous_coordinator
        elif hasattr(self.app, "qa_coordinator"):
            delattr(self.app, "qa_coordinator")

    def _patched_assembly(self, settings_manager):
        """Подменяет всё, что _build_manual_quality_coordinator тянет из
        qa.assembly/qa.handler_factory, лёгкими фейками — без реального
        QA-потока. attach имитирует единственный побочный эффект настоящего
        attach_chapter_qa_coordinator, который важен здесь: запись в
        app.qa_coordinator (и, до неё, собственный внутренний detach — как в
        боевом коде, а не наш явный вызов). Сборка обрывается на
        green_keys() пустым списком точно так же, как настоящий
        _build_manual_quality_coordinator — ДО обращения к attach.
        """
        created = []

        def fake_attach(app, **kwargs):
            marker = object()
            app.qa_coordinator = marker
            created.append(marker)
            return marker

        def fake_detach(app):
            app.qa_coordinator = None

        return created, patch.multiple(
            "gemini_translator.qa.assembly",
            resolve_manual_qa_model=lambda sm, qa_settings: (
                settings_manager.provider,
                settings_manager.model,
            ),
            green_keys=lambda sm, provider, model: list(settings_manager.healthy_keys),
            aiohttp_session_factory=lambda proxy: (lambda: None),
            detect_source_language=lambda text: "en",
            manual_session_settings=lambda sm, proxy: object(),
            embedding_keys_for_session=lambda provider, keys: {},
            attach_chapter_qa_coordinator=fake_attach,
            detach_chapter_qa_coordinator=fake_detach,
        ), patch(
            "gemini_translator.qa.handler_factory.build_qa_handler_factory",
            lambda **kwargs: (lambda *a, **k: None),
        )

    def test_unchanged_settings_keep_the_same_coordinator(self):
        page = _make_page()
        self.addCleanup(_dispose_page, page)
        self.addCleanup(page.deleteLater)
        settings_manager = _FakeSettingsManager("gemini", "gemini-model", ["key-1"])
        page._quality_settings_manager = lambda: settings_manager

        created, assembly_patch, handler_patch = self._patched_assembly(settings_manager)
        with assembly_patch, handler_patch:
            first = page._quality_coordinator()
            second = page._quality_coordinator()

        self.assertIsNotNone(first)
        self.assertIs(first, second)
        self.assertEqual(len(created), 1, "координатор не должен пересобираться зря")

    def test_changed_manual_settings_rebuild_the_coordinator(self):
        page = _make_page()
        self.addCleanup(_dispose_page, page)
        self.addCleanup(page.deleteLater)
        settings_manager = _FakeSettingsManager("gemini", "gemini-model", ["key-1"])
        page._quality_settings_manager = lambda: settings_manager

        created, assembly_patch, handler_patch = self._patched_assembly(settings_manager)
        with assembly_patch, handler_patch:
            first = page._quality_coordinator()

            # Пользователь добавил новый ключ в настройках проверки.
            settings_manager.keys = ["key-1", "key-2"]
            settings_manager.healthy_keys = ["key-1", "key-2"]

            second = page._quality_coordinator()

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNot(
            first,
            second,
            "координатор, собранный на старых ключах, не должен переживать их смену",
        )
        self.assertEqual(len(created), 2)

    def test_changed_model_rebuilds_the_coordinator(self):
        page = _make_page()
        self.addCleanup(_dispose_page, page)
        self.addCleanup(page.deleteLater)
        settings_manager = _FakeSettingsManager("gemini", "gemini-model", ["key-1"])
        page._quality_settings_manager = lambda: settings_manager

        created, assembly_patch, handler_patch = self._patched_assembly(settings_manager)
        with assembly_patch, handler_patch:
            first = page._quality_coordinator()

            # Пользователь сменил «Модель для исправлений».
            settings_manager.model = "gemini-model-2"

            second = page._quality_coordinator()

        self.assertIsNot(first, second)
        self.assertEqual(len(created), 2)

    def test_a_live_translation_sessions_coordinator_is_never_touched(self):
        """Координатор активной сессии перевода — не наш, его не трогаем."""
        page = _make_page()
        self.addCleanup(_dispose_page, page)
        self.addCleanup(page.deleteLater)
        settings_manager = _FakeSettingsManager("gemini", "gemini-model", ["key-1"])
        page._quality_settings_manager = lambda: settings_manager

        session_coordinator = object()
        self.app.qa_coordinator = session_coordinator

        created, assembly_patch, handler_patch = self._patched_assembly(settings_manager)
        with assembly_patch, handler_patch:
            # Смена ключей не должна иметь значения: это координатор сессии,
            # а не наш ручной, и его отпечаток мы никогда не проверяем.
            settings_manager.keys = ["key-1", "key-2"]
            result = page._quality_coordinator()

        self.assertIs(result, session_coordinator)
        self.assertEqual(
            len(created), 0, "чужой координатор сессии не должен пересобираться"
        )

    def test_key_going_red_alone_does_not_rebuild_the_coordinator(self):
        """Ключ, поймавший дневной лимит, не должен трогать координатор.

        Отпечаток строится по НАСТРОЕННЫМ ключам (load_key_statuses), а не по
        green_keys() — та отражает сиюминутное здоровье квоты, а не решение
        пользователя. На версии до этого исправления один ключ, ушедший в
        лимит посреди многочасового прохода, при следующем обращении выглядел
        как «настройки изменились» и валил живой координатор.
        """
        page = _make_page()
        self.addCleanup(_dispose_page, page)
        self.addCleanup(page.deleteLater)
        settings_manager = _FakeSettingsManager(
            "gemini", "gemini-model", ["key-1", "key-2"]
        )
        page._quality_settings_manager = lambda: settings_manager

        created, assembly_patch, handler_patch = self._patched_assembly(settings_manager)
        with assembly_patch, handler_patch:
            first = page._quality_coordinator()

            # Один из ключей поймал дневной лимит по ходу прохода — настройки
            # (settings_manager.keys) при этом НЕ менялись, только их
            # сиюминутное здоровье.
            settings_manager.healthy_keys = ["key-2"]

            second = page._quality_coordinator()

        self.assertIsNotNone(first)
        self.assertIs(
            first,
            second,
            "смена здоровья ключа не должна пересобирать координатор — "
            "настройки не менялись",
        )
        self.assertEqual(
            len(created), 1, "живой проход не должен получать shutdown() из-за квоты"
        )

    def test_rebuild_is_deferred_while_a_pass_is_running(self):
        """Идущий проход не пересобирается, даже если настройки реально сменились."""
        page = _make_page()
        self.addCleanup(_dispose_page, page)
        self.addCleanup(page.deleteLater)
        settings_manager = _FakeSettingsManager("gemini", "gemini-model", ["key-1"])
        page._quality_settings_manager = lambda: settings_manager

        created, assembly_patch, handler_patch = self._patched_assembly(settings_manager)
        with assembly_patch, handler_patch:
            first = page._quality_coordinator()
            page._quality_pass_running = True

            settings_manager.keys = ["key-1", "key-2"]
            settings_manager.healthy_keys = ["key-1", "key-2"]

            second = page._quality_coordinator()

        self.assertIs(
            first,
            second,
            "координатор идущего прохода нельзя пересобирать до его конца",
        )
        self.assertEqual(len(created), 1)

    def test_rebuild_resumes_once_the_pass_ends(self):
        """Отложенная пересборка происходит сразу, как только проход закончился."""
        page = _make_page()
        self.addCleanup(_dispose_page, page)
        self.addCleanup(page.deleteLater)
        settings_manager = _FakeSettingsManager("gemini", "gemini-model", ["key-1"])
        page._quality_settings_manager = lambda: settings_manager

        created, assembly_patch, handler_patch = self._patched_assembly(settings_manager)
        with assembly_patch, handler_patch:
            first = page._quality_coordinator()
            page._quality_pass_running = True
            settings_manager.keys = ["key-1", "key-2"]
            settings_manager.healthy_keys = ["key-1", "key-2"]

            deferred = page._quality_coordinator()

            page._quality_pass_running = False
            second = page._quality_coordinator()

        self.assertIs(first, deferred)
        self.assertIsNot(first, second)
        self.assertEqual(len(created), 2)

    def test_failed_rebuild_keeps_the_coordinator_that_still_works(self):
        """Если новую сборку собрать не удалось, старый координатор остаётся живым.

        До правки detach_chapter_qa_coordinator() вызывался ДО попытки
        собрать замену: стоило второй сборке провалиться (у новой модели
        прямо сейчас нет ни одного зелёного ключа), рабочий координатор уже
        был уничтожен, а взамен не появлялось ничего.
        """
        page = _make_page()
        self.addCleanup(_dispose_page, page)
        self.addCleanup(page.deleteLater)
        settings_manager = _FakeSettingsManager("gemini", "gemini-model", ["key-1"])
        page._quality_settings_manager = lambda: settings_manager

        created, assembly_patch, handler_patch = self._patched_assembly(settings_manager)
        with assembly_patch, handler_patch:
            first = page._quality_coordinator()

            # Пользователь реально сменил модель проверки — а у новой модели
            # прямо сейчас нет ни одного рабочего ключа.
            settings_manager.model = "gemini-model-2"
            settings_manager.healthy_keys = []

            second = page._quality_coordinator()

        self.assertIsNotNone(first)
        self.assertIs(
            second,
            first,
            "не удалось собрать замену — рабочий координатор остаётся, а не исчезает",
        )
        self.assertIs(self.app.qa_coordinator, first)
        self.assertEqual(
            len(created), 1, "неудачная попытка сборки не должна детачить старый"
        )


if __name__ == "__main__":
    unittest.main()
