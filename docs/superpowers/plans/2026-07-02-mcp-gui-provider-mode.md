# MCP GUI Provider Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `MCP сервер` item to the shared AI service selector and swap the key-count card for a compact MCP control card while that item is selected.

**Architecture:** Create a focused compact MCP control widget that reuses the existing `gemini_translator.mcp` client/config modules. Integrate it into the shared `KeyManagementWidget` as a synthetic UI-only provider mode; while selected, the widget hides key metrics and provider-server controls, but preserves the last real translation provider for the rest of the app. Because the main translator, AI glossary generation, AI glossary correction, untranslated fixer, and consistency checker all use `KeyManagementWidget`, the MCP mode appears in every AI workflow without duplicating UI code.

**Tech Stack:** PyQt6 widgets/QThread, existing `gemini_translator.mcp.client`, existing `gemini_translator.mcp.client_install`, unittest/pytest with `QT_QPA_PLATFORM=offscreen`.

---

## File Structure

- Create: `gemini_translator/ui/widgets/mcp_control_widget.py`
  Compact MCP status/action card plus a tiny worker wrapper for start/status/stop/config actions.
- Modify: `gemini_translator/ui/widgets/key_management_widget.py`
  Add the synthetic `MCP сервер` combo item and swap key/MCP cards based on the current combo item. This is the shared integration point for the main translator, AI glossary generation, AI glossary correction, untranslated fixer, and consistency checker.
- Modify: `tests/test_key_management_widget.py`
  Add tests for synthetic provider selection, shared-surface coverage, card swapping, provider-server button hiding, and preserving the last real provider.
- Create: `tests/test_mcp_control_widget.py`
  Add focused tests for the compact MCP card using fake backends, without binding network ports.

The implementation must not modify `api_providers.json`; `MCP сервер` is a UI-only item, not a real translation provider.

Relevant shared-surface call sites that should keep using the same widget:

- `gemini_translator/ui/dialogs/setup.py`
- `gemini_translator/ui/dialogs/glossary_dialogs/ai_generation.py`
- `gemini_translator/ui/dialogs/glossary_dialogs/ai_correction.py`
- `gemini_translator/ui/dialogs/validation_dialogs/untranslated_fixer_dialog.py`
- `gemini_translator/ui/dialogs/consistency_checker.py`

---

### Task 1: Compact MCP Control Widget Skeleton

**Files:**
- Create: `gemini_translator/ui/widgets/mcp_control_widget.py`
- Create: `tests/test_mcp_control_widget.py`

- [ ] **Step 1: Write failing tests for the compact MCP card initial state**

Create `tests/test_mcp_control_widget.py` with:

```python
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from gemini_translator.ui.widgets.mcp_control_widget import (
    McpControlWidget,
    McpStatusSnapshot,
)


class _FakeBackend:
    def status(self):
        return McpStatusSnapshot(running=False, detail="stdio + local daemon")

    def start(self):
        return McpStatusSnapshot(running=True, detail="127.0.0.1:12345")

    def stop(self):
        return McpStatusSnapshot(running=False, detail="stdio + local daemon")

    def codex_config(self):
        return "[mcp_servers.translatorFork]\ncommand = \"python\"\n"


class McpControlWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_initial_state_is_compact_and_off(self):
        widget = McpControlWidget(backend=_FakeBackend())
        self.addCleanup(widget.close)

        self.assertEqual(widget.objectName(), "mcpControlCard")
        self.assertEqual(widget.status_value_label.text(), "Выключен")
        self.assertEqual(widget.detail_label.text(), "stdio + local daemon")
        self.assertEqual(widget.action_button.text(), "Запустить")
        self.assertEqual(widget.config_button.text(), "Codex config")
        self.assertLessEqual(widget.sizeHint().height(), 76)

    def test_apply_running_status_updates_labels(self):
        widget = McpControlWidget(backend=_FakeBackend())
        self.addCleanup(widget.close)

        widget.apply_status(McpStatusSnapshot(running=True, detail="127.0.0.1:5000"))

        self.assertEqual(widget.status_value_label.text(), "Запущен")
        self.assertEqual(widget.detail_label.text(), "127.0.0.1:5000")
        self.assertEqual(widget.action_button.text(), "Остановить")

    def test_apply_error_status_keeps_card_usable(self):
        widget = McpControlWidget(backend=_FakeBackend())
        self.addCleanup(widget.close)

        widget.apply_status(McpStatusSnapshot(running=False, detail="ошибка запуска", error="boom"))

        self.assertEqual(widget.status_value_label.text(), "Ошибка")
        self.assertEqual(widget.detail_label.text(), "ошибка запуска")
        self.assertEqual(widget.action_button.text(), "Запустить")
        self.assertIn("boom", widget.toolTip())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new widget tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_control_widget.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `gemini_translator.ui.widgets.mcp_control_widget`.

- [ ] **Step 3: Implement the compact MCP card skeleton**

Create `gemini_translator/ui/widgets/mcp_control_widget.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from gemini_translator.ui import theme_manager


@dataclass(frozen=True)
class McpStatusSnapshot:
    running: bool
    detail: str = "stdio + local daemon"
    error: str | None = None


class McpControlBackend:
    def status(self) -> McpStatusSnapshot:
        from gemini_translator.mcp.client import DaemonClientError, load_client

        try:
            payload = load_client().status()
        except DaemonClientError as exc:
            return McpStatusSnapshot(running=False, detail="stdio + local daemon", error=str(exc))
        daemon = payload.get("daemon", {}) if isinstance(payload, dict) else {}
        host = daemon.get("host", "127.0.0.1")
        port = daemon.get("port", "")
        return McpStatusSnapshot(running=True, detail=f"{host}:{port}")

    def start(self) -> McpStatusSnapshot:
        from gemini_translator.mcp.client import ensure_daemon_process

        client = ensure_daemon_process()
        payload = client.status()
        daemon = payload.get("daemon", {}) if isinstance(payload, dict) else {}
        host = daemon.get("host", "127.0.0.1")
        port = daemon.get("port", "")
        return McpStatusSnapshot(running=True, detail=f"{host}:{port}")

    def stop(self) -> McpStatusSnapshot:
        from gemini_translator.mcp.client import DaemonClientError, load_client

        try:
            load_client().shutdown()
        except DaemonClientError as exc:
            return McpStatusSnapshot(running=False, detail="stdio + local daemon", error=str(exc))
        return McpStatusSnapshot(running=False, detail="stdio + local daemon")

    def codex_config(self) -> str:
        from gemini_translator.mcp.client_install import build_config_snippet

        snippet = build_config_snippet("codex")
        return str(snippet.get("text", ""))


class McpControlWidget(QtWidgets.QFrame):
    refresh_requested = QtCore.pyqtSignal()

    def __init__(self, parent=None, *, backend=None):
        super().__init__(parent)
        self.backend = backend or McpControlBackend()
        self._running = False
        self.setObjectName("mcpControlCard")
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Minimum, QtWidgets.QSizePolicy.Policy.Minimum)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(8)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(1)

        title_label = QLabel("MCP сервер")
        title_label.setObjectName("keyStatusTitle")
        title_col.addWidget(title_label)

        self.status_value_label = QLabel("Выключен")
        self.status_value_label.setObjectName("keyStatusMetricValue")
        title_col.addWidget(self.status_value_label)
        layout.addLayout(title_col)

        detail_col = QVBoxLayout()
        detail_col.setContentsMargins(0, 0, 0, 0)
        detail_col.setSpacing(1)

        detail_title = QLabel("Daemon")
        detail_title.setObjectName("keyStatusMetricTitle")
        detail_col.addWidget(detail_title)

        self.detail_label = QLabel("stdio + local daemon")
        self.detail_label.setObjectName("mutedLabel")
        self.detail_label.setMinimumWidth(105)
        detail_col.addWidget(self.detail_label)
        layout.addLayout(detail_col)

        self.action_button = QPushButton("Запустить")
        self.action_button.setObjectName("mcpActionButton")
        self.action_button.setFixedHeight(30)
        layout.addWidget(self.action_button)

        self.config_button = QPushButton("Codex config")
        self.config_button.setObjectName("mcpConfigButton")
        self.config_button.setFixedHeight(30)
        layout.addWidget(self.config_button)

        self.apply_status(McpStatusSnapshot(running=False))

    def apply_status(self, snapshot: McpStatusSnapshot) -> None:
        self._running = bool(snapshot.running) and not snapshot.error
        if snapshot.error:
            self.status_value_label.setText("Ошибка")
            self.setToolTip(snapshot.error)
        elif self._running:
            self.status_value_label.setText("Запущен")
            self.setToolTip("")
        else:
            self.status_value_label.setText("Выключен")
            self.setToolTip("")
        self.detail_label.setText(snapshot.detail or "stdio + local daemon")
        self.action_button.setText("Остановить" if self._running else "Запустить")
        self._apply_button_style()

    def _apply_button_style(self) -> None:
        if self._running:
            color = theme_manager.color("danger")
        else:
            color = theme_manager.color("success")
        self.action_button.setStyleSheet(
            f"QPushButton {{ background-color: {color}; color: {theme_manager.color('accent_text')}; "
            "font-weight: bold; padding: 4px 9px; border-radius: 4px; }}"
        )
```

- [ ] **Step 4: Run the widget tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_control_widget.py -q
```

Expected: PASS with `3 passed`.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add gemini_translator/ui/widgets/mcp_control_widget.py tests/test_mcp_control_widget.py
git commit -m "Add compact MCP control widget"
```

---

### Task 2: MCP Card Actions And Config Copy

**Files:**
- Modify: `gemini_translator/ui/widgets/mcp_control_widget.py`
- Modify: `tests/test_mcp_control_widget.py`

- [ ] **Step 1: Add failing tests for action dispatch and config copying**

Append to `tests/test_mcp_control_widget.py`:

```python
class _ActionBackend(_FakeBackend):
    def __init__(self):
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1
        return McpStatusSnapshot(running=True, detail="127.0.0.1:4567")

    def stop(self):
        self.stopped += 1
        return McpStatusSnapshot(running=False, detail="stdio + local daemon")

    def codex_config(self):
        return "[mcp_servers.translatorFork]\ncommand = \"python\"\n"


def test_action_button_runs_start_then_stop():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    backend = _ActionBackend()
    widget = McpControlWidget(backend=backend)
    app.processEvents()

    widget._execute_action_sync("toggle")
    assert backend.started == 1
    assert widget.status_value_label.text() == "Запущен"
    assert widget.action_button.text() == "Остановить"

    widget._execute_action_sync("toggle")
    assert backend.stopped == 1
    assert widget.status_value_label.text() == "Выключен"
    assert widget.action_button.text() == "Запустить"


def test_copy_codex_config_uses_clipboard():
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    backend = _ActionBackend()
    widget = McpControlWidget(backend=backend)

    copied = widget.copy_codex_config()

    assert copied.startswith("[mcp_servers.translatorFork]")
    assert QtWidgets.QApplication.clipboard().text() == copied
```

These pytest-style functions can live in the same file after the unittest class; the repo already runs the file through pytest.

- [ ] **Step 2: Run the action tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_control_widget.py::test_action_button_runs_start_then_stop tests/test_mcp_control_widget.py::test_copy_codex_config_uses_clipboard -q
```

Expected: FAIL with `AttributeError` for `_execute_action_sync` or `copy_codex_config`.

- [ ] **Step 3: Implement synchronous action core plus button wiring**

Modify `McpControlWidget.__init__` in `gemini_translator/ui/widgets/mcp_control_widget.py` after `_apply_button_style()` setup:

```python
        self.action_button.clicked.connect(lambda: self._execute_action_sync("toggle"))
        self.config_button.clicked.connect(self.copy_codex_config)
```

Add these methods to `McpControlWidget`:

```python
    def _execute_action_sync(self, action: str) -> McpStatusSnapshot:
        try:
            if action == "status":
                snapshot = self.backend.status()
            elif action == "toggle" and self._running:
                snapshot = self.backend.stop()
            elif action == "toggle":
                snapshot = self.backend.start()
            else:
                snapshot = McpStatusSnapshot(running=False, detail="Неизвестное действие", error=str(action))
        except Exception as exc:
            snapshot = McpStatusSnapshot(running=False, detail="ошибка MCP", error=str(exc))
        self.apply_status(snapshot)
        return snapshot

    def refresh_status(self) -> McpStatusSnapshot:
        return self._execute_action_sync("status")

    def copy_codex_config(self) -> str:
        try:
            text = self.backend.codex_config()
        except Exception as exc:
            self.apply_status(McpStatusSnapshot(running=self._running, detail="ошибка config", error=str(exc)))
            return ""
        QtWidgets.QApplication.clipboard().setText(text)
        self.config_button.setToolTip("Codex config скопирован")
        return text
```

The first implementation is synchronous to establish behavior under tests. Task 5 adds a worker wrapper for non-blocking UI actions before the feature is complete.

- [ ] **Step 4: Run widget tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_control_widget.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add gemini_translator/ui/widgets/mcp_control_widget.py tests/test_mcp_control_widget.py
git commit -m "Wire MCP control widget actions"
```

---

### Task 3: Synthetic MCP Provider In KeyManagementWidget

**Files:**
- Modify: `gemini_translator/ui/widgets/key_management_widget.py`
- Modify: `tests/test_key_management_widget.py`

- [ ] **Step 1: Add failing tests for the synthetic provider item**

Append to `KeyManagementWidgetProviderModeTests` in `tests/test_key_management_widget.py`:

```python
    def test_provider_combo_contains_mcp_server_item(self):
        widget = KeyManagementWidget(_KeySettingsStub())
        self.addCleanup(widget.close)

        index = widget.provider_combo.findData("__mcp_server__")

        self.assertGreaterEqual(index, 0)
        self.assertEqual(widget.provider_combo.itemText(index), "MCP сервер")

    def test_shared_ai_surfaces_still_use_key_management_widget(self):
        root = Path(__file__).resolve().parents[1]
        surface_files = [
            root / "gemini_translator/ui/dialogs/setup.py",
            root / "gemini_translator/ui/dialogs/glossary_dialogs/ai_generation.py",
            root / "gemini_translator/ui/dialogs/glossary_dialogs/ai_correction.py",
            root / "gemini_translator/ui/dialogs/validation_dialogs/untranslated_fixer_dialog.py",
            root / "gemini_translator/ui/dialogs/consistency_checker.py",
        ]

        for path in surface_files:
            source = path.read_text(encoding="utf-8")
            self.assertIn("KeyManagementWidget", source, str(path))
```

Also add this import near the top of `tests/test_key_management_widget.py`:

```python
from pathlib import Path
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_key_management_widget.py::KeyManagementWidgetProviderModeTests::test_provider_combo_contains_mcp_server_item -q
```

Expected: FAIL because `findData("__mcp_server__")` returns `-1`. The shared-surface assertion should already pass and documents why a single `KeyManagementWidget` integration covers the main translator, AI glossary generation, AI glossary correction, untranslated fixing, and consistency checking.

- [ ] **Step 3: Add constants and combo item**

Modify imports at the top of `gemini_translator/ui/widgets/key_management_widget.py`:

```python
from .mcp_control_widget import McpControlWidget
```

Add module constants after imports:

```python
MCP_PROVIDER_ID = "__mcp_server__"
MCP_PROVIDER_NAME = "MCP сервер"
```

In `KeyManagementWidget.init_ui()`, after the loop that adds visible providers:

```python
        self.provider_combo.addItem(MCP_PROVIDER_NAME, userData=MCP_PROVIDER_ID)
        self._last_real_provider_id = self.provider_combo.itemData(0)
```

- [ ] **Step 4: Run the new provider item test**

Run:

```bash
.venv/bin/python -m pytest tests/test_key_management_widget.py::KeyManagementWidgetProviderModeTests::test_provider_combo_contains_mcp_server_item -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add gemini_translator/ui/widgets/key_management_widget.py tests/test_key_management_widget.py
git commit -m "Add MCP server provider option"
```

---

### Task 4: Swap Key Status Card For MCP Card

**Files:**
- Modify: `gemini_translator/ui/widgets/key_management_widget.py`
- Modify: `tests/test_key_management_widget.py`

- [ ] **Step 1: Add failing tests for card swapping and provider preservation**

Append to `KeyManagementWidgetProviderModeTests`:

```python
    def test_mcp_provider_swaps_key_status_for_mcp_card(self):
        widget = KeyManagementWidget(_KeySettingsStub())
        self.addCleanup(widget.close)

        normal_provider = widget.get_selected_provider()
        mcp_index = widget.provider_combo.findData("__mcp_server__")
        widget.provider_combo.setCurrentIndex(mcp_index)

        self.assertEqual(widget.get_selected_provider(), normal_provider)
        self.assertFalse(widget.key_status_card.isVisible())
        self.assertTrue(widget.mcp_control_card.isVisible())
        self.assertFalse(widget.server_button.isVisible())
        self.assertFalse(widget.available_keys_group.isEnabled())
        self.assertFalse(widget.active_keys_group.isEnabled())

    def test_switching_back_from_mcp_restores_key_status_card(self):
        widget = KeyManagementWidget(_KeySettingsStub())
        self.addCleanup(widget.close)

        first_index = 0
        mcp_index = widget.provider_combo.findData("__mcp_server__")
        widget.provider_combo.setCurrentIndex(mcp_index)
        widget.provider_combo.setCurrentIndex(first_index)

        self.assertTrue(widget.key_status_card.isVisible())
        self.assertFalse(widget.mcp_control_card.isVisible())
        self.assertTrue(widget.available_keys_group.isEnabled())
        self.assertTrue(widget.active_keys_group.isEnabled())
```

- [ ] **Step 2: Run the card swap tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_key_management_widget.py::KeyManagementWidgetProviderModeTests::test_mcp_provider_swaps_key_status_for_mcp_card tests/test_key_management_widget.py::KeyManagementWidgetProviderModeTests::test_switching_back_from_mcp_restores_key_status_card -q
```

Expected: FAIL with `AttributeError` for `mcp_control_card` or failed visibility assertions.

- [ ] **Step 3: Create the MCP control card beside the key status card**

In `KeyManagementWidget.init_ui()`, after `self.key_status_card = self._create_key_status_card()`:

```python
        self.mcp_control_card = McpControlWidget(self)
        self.mcp_control_card.setVisible(False)
```

In the provider row layout, after adding `self.key_status_card`:

```python
        provider_layout.addWidget(self.mcp_control_card, 0)
```

- [ ] **Step 4: Implement raw-provider helpers and MCP mode application**

Add these methods to `KeyManagementWidget`:

```python
    def _current_raw_provider(self) -> str:
        return self.provider_combo.currentData()

    def _is_mcp_provider_selected(self) -> bool:
        return self._current_raw_provider() == MCP_PROVIDER_ID

    def _apply_mcp_provider_mode(self) -> None:
        self.key_status_card.setVisible(False)
        self.mcp_control_card.setVisible(True)
        self.server_button.setVisible(False)
        self.available_keys_group.setEnabled(False)
        self.active_keys_group.setEnabled(False)
        self.available_keys_group.setTitle("2. MCP-сервер")
        self.active_keys_group.setTitle("3. MCP управляет задачами через daemon")
        self.mcp_control_card.refresh_status()

    def _restore_key_provider_mode(self) -> None:
        self.key_status_card.setVisible(True)
        self.mcp_control_card.setVisible(False)
        self.available_keys_group.setEnabled(True)
        self.active_keys_group.setEnabled(True)
```

- [ ] **Step 5: Update provider change flow**

Modify `_on_provider_changed()` in `key_management_widget.py` to start with:

```python
        provider_id = self.provider_combo.itemData(index)
        provider_display_name = self.provider_combo.itemText(index)

        if provider_id == MCP_PROVIDER_ID:
            self._apply_mcp_provider_mode()
            return

        self._last_real_provider_id = provider_id
        self._restore_key_provider_mode()
```

Then keep the existing normal-provider logic after those lines:

```python
        self.available_keys_group.setTitle(
            f"2. Доступные ключи ({provider_display_name})")
        self._apply_provider_mode(provider_id, provider_display_name)
        self.bus.event_posted.emit({
            'event': 'provider_changed',
            'source': 'KeyManagementWidget',
            'data': {
                'provider_id': provider_id,
                'provider_widget_id': id(self),
            }
        })
        self._load_and_refresh_keys()
        self._update_server_button_visibility()
```

- [ ] **Step 6: Preserve the last real provider**

Change `get_selected_provider()` to:

```python
    def get_selected_provider(self) -> str:
        provider_id = self.provider_combo.currentData()
        if provider_id == MCP_PROVIDER_ID:
            return self._last_real_provider_id
        return provider_id
```

Change `_update_server_button_visibility()` to hide provider-server controls in MCP mode:

```python
    def _update_server_button_visibility(self):
        if self._is_mcp_provider_selected():
            self.server_button.setVisible(False)
            return
        if not self.server_manager:
            self.server_button.setVisible(False)
            return
        provider_id = self.provider_combo.currentData()
        provider_config = api_config.api_providers().get(provider_id, {})
        has_server = "server_class" in provider_config
        self.server_button.setVisible(has_server)
        if has_server:
            is_running = self.server_manager.is_server_running()
            message = "running" if is_running else None
            self._update_server_button(is_running, message)
```

- [ ] **Step 7: Run key management tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_key_management_widget.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 4**

Run:

```bash
git add gemini_translator/ui/widgets/key_management_widget.py tests/test_key_management_widget.py
git commit -m "Swap MCP provider controls into key row"
```

---

### Task 5: Move MCP Actions Off The UI Thread

**Files:**
- Modify: `gemini_translator/ui/widgets/mcp_control_widget.py`
- Modify: `tests/test_mcp_control_widget.py`

- [ ] **Step 1: Add failing test that button clicks dispatch a worker method**

Append to `tests/test_mcp_control_widget.py`:

```python
def test_action_button_dispatches_background_action():
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    backend = _ActionBackend()
    widget = McpControlWidget(backend=backend)
    dispatched = []
    widget._dispatch_action = dispatched.append

    widget.action_button.click()

    assert dispatched == ["toggle"]
    assert backend.started == 0
```

- [ ] **Step 2: Run the dispatch test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_control_widget.py::test_action_button_dispatches_background_action -q
```

Expected: FAIL because the button still calls `_execute_action_sync()` directly and increments `backend.started`.

- [ ] **Step 3: Add a QThread worker and dispatch method**

Add this worker class to `mcp_control_widget.py` above `McpControlWidget`:

```python
class McpActionWorker(QtCore.QObject):
    finished = QtCore.pyqtSignal(object)

    def __init__(self, backend, action: str, running: bool):
        super().__init__()
        self.backend = backend
        self.action = action
        self.running = running

    @QtCore.pyqtSlot()
    def run(self) -> None:
        try:
            if self.action == "status":
                snapshot = self.backend.status()
            elif self.action == "toggle" and self.running:
                snapshot = self.backend.stop()
            elif self.action == "toggle":
                snapshot = self.backend.start()
            else:
                snapshot = McpStatusSnapshot(running=False, detail="Неизвестное действие", error=str(self.action))
        except Exception as exc:
            snapshot = McpStatusSnapshot(running=False, detail="ошибка MCP", error=str(exc))
        self.finished.emit(snapshot)
```

Modify button wiring in `McpControlWidget.__init__`:

```python
        self.action_button.clicked.connect(lambda: self._dispatch_action("toggle"))
```

Add `self._worker_thread = None` and `self._worker = None` in `__init__` before connecting signals.

Add this method:

```python
    def _dispatch_action(self, action: str) -> None:
        if self._worker_thread is not None:
            return
        self.action_button.setEnabled(False)
        thread = QtCore.QThread(self)
        worker = McpActionWorker(self.backend, action, self._running)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_worker_finished)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._worker_thread = thread
        self._worker = worker
        thread.start()

    def _on_worker_finished(self, snapshot: McpStatusSnapshot) -> None:
        self.apply_status(snapshot)
        self.action_button.setEnabled(True)
        thread = self._worker_thread
        self._worker = None
        self._worker_thread = None
        if thread is not None:
            thread.quit()
```

Keep `_execute_action_sync()` for deterministic unit tests and direct status refresh tests.

- [ ] **Step 4: Run MCP widget tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_control_widget.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

Run:

```bash
git add gemini_translator/ui/widgets/mcp_control_widget.py tests/test_mcp_control_widget.py
git commit -m "Run MCP GUI actions in background"
```

---

### Task 6: Final Verification And GUI Smoke

**Files:**
- Modify only if verification finds a defect:
  - `gemini_translator/ui/widgets/key_management_widget.py`
  - `gemini_translator/ui/widgets/mcp_control_widget.py`
  - related tests

- [ ] **Step 1: Run focused GUI tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_key_management_widget.py tests/test_mcp_control_widget.py -q
```

Expected: PASS.

- [ ] **Step 2: Run MCP regression tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_daemon.py tests/test_mcp_client_install.py -q
```

Expected: PASS.

- [ ] **Step 3: Run existing CLI regression tests**

Run:

```bash
GT_DISABLE_LOCAL_MODEL_DISCOVERY=1 .venv/bin/python -m pytest tests/test_cli_tools.py -q
```

Expected: PASS.

- [ ] **Step 4: Run headless import smoke**

Run:

```bash
QT_QPA_PLATFORM=offscreen GT_DISABLE_LOCAL_MODEL_DISCOVERY=1 .venv/bin/python -c "from PyQt6 import QtWidgets; from gemini_translator.ui.widgets.key_management_widget import KeyManagementWidget; from gemini_translator.utils.settings import SettingsManager; app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([]); w=KeyManagementWidget(SettingsManager()); assert w.provider_combo.findData('__mcp_server__') >= 0; w.close(); print('ok')"
```

Expected: stdout contains `ok`.

- [ ] **Step 5: Verify shared AI surfaces route through KeyManagementWidget**

Run:

```bash
rg -n "KeyManagementWidget\\(" gemini_translator/ui/dialogs/setup.py gemini_translator/ui/dialogs/glossary_dialogs/ai_generation.py gemini_translator/ui/dialogs/glossary_dialogs/ai_correction.py gemini_translator/ui/dialogs/validation_dialogs/untranslated_fixer_dialog.py gemini_translator/ui/dialogs/consistency_checker.py
```

Expected: output contains one or more `KeyManagementWidget(` call sites in each of the five files. This confirms the MCP selector mode is shared across the main translator, AI glossary generation, AI glossary correction, untranslated fixing, and consistency checking.

- [ ] **Step 6: Check diff hygiene**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only intended files are modified or untracked visual-companion files remain outside the commit.

- [ ] **Step 7: Commit any final fixups**

If Task 6 required code fixes, commit them:

```bash
git add gemini_translator/ui/widgets/key_management_widget.py gemini_translator/ui/widgets/mcp_control_widget.py tests/test_key_management_widget.py tests/test_mcp_control_widget.py
git commit -m "Polish MCP GUI provider mode"
```

If Task 6 required no code fixes, do not create an empty commit.
