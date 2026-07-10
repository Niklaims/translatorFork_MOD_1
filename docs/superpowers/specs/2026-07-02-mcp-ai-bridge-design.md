# MCP AI Bridge Design

## Goal

When the GUI is in MCP mode, the existing AI workflows must be able to use the connected AI application as the model backend. Translation, glossary generation/correction, untranslated fixing, and consistency checks should keep using the existing worker/task pipeline, but each prompt should be answered by the MCP-connected AI client instead of an API-key provider.

## Non-Goals

- Do not rewrite the five GUI workflows as separate MCP tools.
- Do not fake Gemini keys or route MCP through an old provider.
- Do not require the user to change ports on every app restart.
- Do not depend on a specific client UI beyond the MCP protocol path already configured through `http://127.0.0.1:65016/sse`.

## Architecture

Add a new hidden provider with id `__mcp_server__` and handler class `McpApiHandler`. The GUI already exposes `MCP сервер` as a selectable service; when that mode is selected, session settings should use this provider. The normal `TranslationEngine` then starts workers with one virtual key and the new handler returns plain text responses, so existing parsers and task flows keep working.

The handler talks to the local MCP daemon through a token-protected HTTP endpoint. The daemon chooses the best available bridge:

1. **SSE sampling path.** If a connected SSE client advertised sampling capability during `initialize`, the daemon sends a server-to-client JSON-RPC request using `sampling/createMessage` over that same SSE stream and waits for the JSON-RPC response posted back to `/messages`.
2. **Inbox fallback path.** If no sampling-capable client is connected, the daemon creates a pending GUI AI task. MCP tools let the connected AI client claim the prompt and submit the result. The GUI worker waits until the result, failure, cancellation, or timeout.

Sampling is preferred because it gives the desired one-click GUI behavior. Inbox fallback is still useful for clients that expose tools but do not implement MCP sampling.

## Components

- `gemini_translator/mcp/ai_bridge.py`
  - Stores pending GUI AI requests in the MCP state directory.
  - Provides request creation, claim, completion, failure, wait, timeout cleanup, and safe redaction helpers.

- `gemini_translator/mcp/daemon.py`
  - Adds `POST /ai/completions` for GUI workers.
  - Tracks pending server-to-client JSON-RPC requests for SSE sampling.
  - Detects JSON-RPC responses posted to `/messages` and routes them to waiting sampling calls.

- `gemini_translator/mcp/server.py`
  - Adds tools for inbox fallback: `list_gui_ai_tasks`, `claim_gui_ai_task`, `submit_gui_ai_task_result`, and `fail_gui_ai_task`.
  - Keeps current job tools intact.

- `gemini_translator/api/handlers/mcp.py`
  - Implements `McpApiHandler`.
  - Sends prompt, optional system instruction, timeout, temperature, and max output hints to the daemon.
  - Returns the assistant text as a normal API response.

- `config/api_providers.json`, `gemini_translator/api/factory.py`, `gemini_translator/api/handlers/__init__.py`
  - Register hidden provider `__mcp_server__`.

- GUI settings code
  - MCP mode should pass provider `__mcp_server__`, one virtual active key, and model config for the hidden provider.
  - Model settings remain visually disabled because the real model is selected in the AI application.

## Data Flow

1. User chooses `MCP сервер` in the GUI and starts a workflow.
2. GUI settings contain `provider="__mcp_server__"` and `api_keys=["__mcp_client_session__"]`.
3. `TranslationEngine` starts normally.
4. Worker calls `McpApiHandler.execute_api_call(prompt, ...)`.
5. Handler posts to daemon `/ai/completions`.
6. Daemon uses sampling if available; otherwise it creates an inbox task and waits.
7. AI client returns text.
8. Handler returns text to worker.
9. Existing response parser stores translated text/glossary/fixes exactly as before.

## Error Handling

- No connected clients: handler raises `NetworkError` with a clear MCP message.
- Connected client but no sampling and no inbox result before timeout: handler raises `NetworkError`.
- Sampling response JSON-RPC error: handler raises `NetworkError` with sanitized error text.
- Empty assistant text: handler raises `ValidationFailedError`.
- User stop/cancel: worker cancellation propagates normally; daemon wait endpoints should release on timeout or failed request.

## Testing

- Unit-test bridge store lifecycle.
- Unit-test SSE sampling round trip by opening `/sse`, posting `initialize` with sampling capability, calling `/ai/completions`, and posting a synthetic sampling response.
- Unit-test inbox tools claim/submit/fail.
- Unit-test `McpApiHandler` with a fake daemon client.
- Unit-test GUI settings in MCP mode produce virtual key and provider config.
- Run existing MCP daemon/server/widget tests and targeted translation-engine tests.
