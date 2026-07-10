# MCP AI Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real MCP-backed AI provider so GUI workflows can get model responses from the connected AI application.

**Architecture:** Implement the bridge at provider/handler level, not per GUI window. `McpApiHandler` sends prompts to the daemon; daemon prefers SSE `sampling/createMessage` and falls back to a tool-claimable inbox.

**Tech Stack:** Python, PyQt6 worker pipeline, MCP JSON-RPC over SSE, local daemon HTTP endpoints, pytest/unittest.

---

### Task 1: Bridge Store

**Files:**
- Create: `gemini_translator/mcp/ai_bridge.py`
- Test: `tests/test_mcp_ai_bridge.py`

- [ ] Add `GuiAiTask` dataclass with fields `id`, `status`, `created_at`, `updated_at`, `prompt`, `system_instruction`, `metadata`, `result_text`, `error`, `claimed_by`.
- [ ] Implement `create_gui_ai_task(state_dir, payload)`, `list_gui_ai_tasks(state_dir)`, `claim_gui_ai_task(state_dir, task_id, client_name)`, `complete_gui_ai_task(state_dir, task_id, text)`, `fail_gui_ai_task(state_dir, task_id, error)`, and `wait_for_gui_ai_task(state_dir, task_id, timeout_sec)`.
- [ ] Write tests for create/list, claim idempotence, complete, fail, timeout.
- [ ] Run `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_mcp_ai_bridge.py -q`.

### Task 2: SSE Sampling

**Files:**
- Modify: `gemini_translator/mcp/client_sessions.py`
- Modify: `gemini_translator/mcp/daemon.py`
- Test: `tests/test_mcp_daemon.py`

- [ ] Store client capabilities on `initialize`, including `supports_sampling`.
- [ ] Add daemon pending request map keyed by JSON-RPC id.
- [ ] Add `McpDaemon.request_ai_completion(payload)` and token-protected `POST /ai/completions`.
- [ ] If an SSE session supports sampling, enqueue JSON-RPC request `{method:"sampling/createMessage"}` on that session queue and wait for response.
- [ ] In `/messages`, detect JSON-RPC responses for daemon-originated ids and deliver them to the waiting request instead of passing them to `McpStdioServer`.
- [ ] Extract assistant text from `result.content.text` or content arrays.
- [ ] Tests: sampling-capable SSE client receives request, posts response, `/ai/completions` returns text.

### Task 3: Inbox Fallback Tools

**Files:**
- Modify: `gemini_translator/mcp/server.py`
- Modify: `gemini_translator/mcp/daemon.py`
- Test: `tests/test_mcp_server.py`
- Test: `tests/test_mcp_daemon.py`

- [ ] Add tool definitions: `list_gui_ai_tasks`, `claim_gui_ai_task`, `submit_gui_ai_task_result`, `fail_gui_ai_task`.
- [ ] Add methods to `_DaemonMcpClient` and `DaemonClient` for inbox calls.
- [ ] If no sampling-capable client exists, `/ai/completions` creates an inbox task and waits.
- [ ] Tests: tools list includes inbox tools; claim/submit returns result to waiting `/ai/completions`; fail returns an error payload.

### Task 4: MCP API Handler

**Files:**
- Create: `gemini_translator/api/handlers/mcp.py`
- Modify: `gemini_translator/api/handlers/__init__.py`
- Modify: `gemini_translator/api/factory.py`
- Modify: `config/api_providers.json`
- Test: `tests/test_mcp_api_handler.py`

- [ ] Add hidden provider `__mcp_server__`, `requires_api_key=false`, `placeholder_api_key="__mcp_client_session__"`, one model `MCP Client`, handler `McpApiHandler`, async provider, base timeout.
- [ ] Implement `McpApiHandler.execute_api_call()` so it does not increment real key counters and returns daemon result text.
- [ ] Pass prompt, system instruction, temperature override, max output tokens, and operation context metadata.
- [ ] Tests: handler returns daemon text; empty text raises validation; daemon error raises network error.

### Task 5: GUI Session Settings

**Files:**
- Modify: `gemini_translator/ui/widgets/key_management_widget.py`
- Modify: `gemini_translator/ui/widgets/model_settings_widget.py`
- Modify: `gemini_translator/ui/dialogs/setup.py`
- Modify: `gemini_translator/ui/dialogs/glossary_dialogs/ai_generation.py`
- Modify: `gemini_translator/ui/dialogs/glossary_dialogs/ai_correction.py`
- Modify: `gemini_translator/ui/dialogs/validation_dialogs/untranslated_fixer_dialog.py`
- Modify: `gemini_translator/ui/dialogs/consistency_checker.py`
- Test: `tests/test_key_management_widget.py`
- Test: `tests/test_model_settings_widget.py`
- Test: `tests/test_translation_engine_mcp_mode.py`

- [ ] In MCP mode, `get_active_keys()` returns `["__mcp_client_session__"]` when a client is connected.
- [ ] In MCP mode, model settings return model `MCP Client` for settings but keep the UI placeholder visible.
- [ ] Remove the current `TranslationEngine` guard that blocks MCP mode once the handler exists.
- [ ] Ensure all five surfaces resolve `model_config` for `MCP Client`.
- [ ] Tests: MCP mode starts through `TranslationEngine` without the “Нет доступных API ключей” guard.

### Task 6: Verification

**Files:**
- No new files.

- [ ] Run targeted tests:
  `QT_QPA_PLATFORM=offscreen GT_DISABLE_LOCAL_MODEL_DISCOVERY=1 .venv/bin/python -m pytest tests/test_mcp_ai_bridge.py tests/test_mcp_api_handler.py tests/test_mcp_server.py tests/test_mcp_daemon.py tests/test_key_management_widget.py tests/test_model_settings_widget.py tests/test_translation_engine_mcp_mode.py -q`
- [ ] If daemon tests fail with localhost bind `PermissionError`, rerun that test file with escalated local bind permissions.
- [ ] Run `git diff --check`.
- [ ] Print config sanity:
  `GT_DISABLE_LOCAL_MODEL_DISCOVERY=1 .venv/bin/python -m gemini_translator.mcp config --client antigravity`
