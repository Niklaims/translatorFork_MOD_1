# Translator MCP Service Design

## Goal

Add a standard MCP integration for translatorFork_MOD so desktop AI clients such as Codex, Claude Desktop, Antigravity, and other MCP-compatible apps can ask the translator to start long-running AI work without putting book text, model responses, or full review output into the chat context.

The first implementation targets EPUB project workflows that already have headless or near-headless execution paths:

- Translation.
- AI glossary generation.
- AI glossary review/correction.
- Untranslated residue fixing.
- AI consistency check and optional auto-fix.
- EPUB build from translated project files.
- A full pipeline that can chain these operations.

The MCP interface returns job ids, summaries, status, log tails, and output file paths. The application continues to save work to disk using the same project files and translated chapter files as normal app workflows.

## Current Code Facts

- `gemini_translator/cli.py` already exposes headless commands for `translate`, `glossary-generate`, `consistency`, `untranslated-scan`, `untranslated-fix`, and `build-epub`.
- The CLI has `HeadlessRuntime`, which starts the PyQt application in offscreen mode and can include the real `TranslationEngine`.
- Heavy tasks can be launched as subprocesses instead of being executed inside the MCP request handler.
- The UI key/service screen already treats providers without real API keys as virtual sessions, but the MCP service should not be implemented as a model provider in V1. It should be a separate local automation surface.
- No MCP runtime dependency is currently present in `pyproject.toml`, so implementation must either add a small MCP server dependency or implement the minimal stdio JSON-RPC surface in-repo.

## Chosen Architecture

Use a long-running local daemon plus a thin standard MCP stdio server.

The MCP client launches:

```text
desktop AI app -> translator-mcp-server over stdio
```

The stdio server talks to:

```text
translator-mcp-daemon -> durable job queue -> subprocess workers -> gemini_translator.cli commands
```

This keeps the MCP process lightweight and compatible with clients that expect local stdio MCP servers. The daemon owns queue state, cancellation, logs, and recovery. Worker subprocesses run the existing translator CLI commands and write their JSON summaries, stdout, stderr, and generated project files to disk.

## Components

### `gemini_translator/mcp/server.py`

Standard MCP entrypoint.

Responsibilities:

- Register MCP tools.
- Validate tool arguments.
- Start the daemon automatically when needed.
- Forward requests to the daemon.
- Return compact JSON-safe responses.
- Keep stdout reserved for MCP protocol messages.
- Write diagnostics only to stderr or daemon log files.

### `gemini_translator/mcp/daemon.py`

Long-running local service.

Responsibilities:

- Maintain job state.
- Serialize state to disk.
- Start and monitor worker subprocesses.
- Expose a local control API for the stdio server.
- Recover jobs after restart by marking interrupted running jobs as failed with an explanatory reason.
- Enforce a configurable concurrency limit, defaulting to one active heavy translator job.

The local control API should prefer a Unix domain socket on macOS/Linux and named pipe or localhost loopback on Windows. If a platform-specific socket is not ready in the first implementation slice, use localhost loopback with a random per-user token stored in the daemon state directory.

### `gemini_translator/mcp/jobs.py`

Pure job model and persistence.

Responsibilities:

- Define job ids.
- Store job metadata.
- Store command argv.
- Store status transitions.
- Store log and result paths.
- Provide load/save helpers that can be unit-tested without Qt or network access.

### `gemini_translator/mcp/client_install.py`

Client installer and config snippet generator.

Responsibilities:

- Generate a stdio MCP config for the current checkout or installed package.
- Support `codex`, `claude`, `antigravity`, and `generic`.
- Make a timestamped backup before editing any detected config file.
- Avoid overwriting unrelated existing MCP servers.
- Print a manual config snippet when a client path is unknown or the config shape is unsupported.

### CLI Entry Points

Add command routes under the existing CLI or a small new module:

- `translator-mcp server`
- `translator-mcp daemon start`
- `translator-mcp daemon stop`
- `translator-mcp daemon status`
- `translator-mcp install --client codex|claude|antigravity|generic`
- `translator-mcp config --client codex|claude|antigravity|generic`

The V1 executable form is `python -m gemini_translator.mcp ...`. A packaged `translator-mcp` alias is optional packaging work and is not required for the daemon or MCP tools to function.

## MCP Tools

### `translator_status`

Returns:

- App version if available.
- Daemon status.
- Queue counts.
- Active jobs.
- Saved provider/model summary without exposing API keys.

### `start_translation`

Starts a headless translation job.

Arguments:

- `epub`: source EPUB path.
- `project`: translator project folder.
- `chapters`: `pending`, `all`, or `translated`; default `pending`.
- `chapter`: optional repeated filters.
- `offset`, `limit`.
- Provider/model/key options matching the existing CLI.
- `mode`, `task_size`, `splits`, `force_accept`, `json_epub`, `prompt_file`, `glossary`, `settings_json`.

Returns:

- `job_id`.
- Planned command name.
- Project and EPUB paths.
- Initial status.

### `start_glossary_generation`

Starts AI glossary generation.

Arguments mirror `glossary-generate`, including:

- `batch_size`.
- `merge_mode`.
- `new_terms_limit`.
- `glossary_prompt_file`.

Returns a job id. `get_job_status` reports glossary result counts from the CLI JSON summary after the job finishes.

### `start_glossary_review_or_correction`

Starts AI glossary correction/review as a background job.

V1 implementation can be split:

- If a reliable headless correction path already exists during implementation, wire it directly.
- If the current correction path is still UI-only, expose the tool but return a structured `unsupported_in_this_build` response with the exact reason and the implementation status.

The tool must not silently open a modal UI or require user clicks.

### `start_untranslated_fix`

Starts AI fixing for untranslated residue.

Arguments mirror `untranslated-fix`.

Default behavior writes changes to disk. `dry_run` is available but defaults to false because the requested behavior is to save results like normal app work.

### `start_consistency_check`

Starts AI consistency analysis and optional auto-fix.

Arguments mirror `consistency`, including:

- `suffix`.
- `consistency_mode`.
- `glossary_first`.
- `chunk_size`.
- `no_source`.
- `fix`.
- `write`.
- `confidences`.

For "check and save" requests, the MCP tool should set `fix=true` and `write=true` only when the user explicitly asks for fixes or uses the full pipeline preset. Pure checks should not rewrite translated files.

### `start_epub_build`

Builds an EPUB from translated project files.

Arguments mirror `build-epub`.

### `start_full_pipeline`

Creates a parent pipeline job with child jobs.

Default V1 pipeline:

1. Optional AI glossary generation.
2. Translation.
3. Optional untranslated fix.
4. Optional consistency check and auto-fix.
5. Optional EPUB build.

The pipeline job stores each child job id and stops on failure unless `continue_on_error` is true.

### `get_job_status`

Returns:

- Job status.
- Current phase.
- Exit code if finished.
- Started/finished timestamps.
- Compact command summary.
- Last N log lines.
- Result JSON summary if finished.
- Paths to stdout, stderr, result JSON, and generated project/output files.

### `list_jobs`

Lists recent jobs with filters by status, project, type, and time limit.

### `cancel_job`

Requests cancellation. The daemon terminates the worker subprocess and marks the job as cancelled. For translator workers, cancellation is best-effort because the current CLI commands may be inside Qt event loops or provider calls.

### `install_mcp_client`

Installs or prints configuration for desktop clients.

Arguments:

- `client`: `codex`, `claude`, `antigravity`, or `generic`.
- `mode`: `auto`, `print`, or `write`.
- `config_path`: optional explicit path.
- `server_name`: default `translatorFork`.

Returns:

- Whether a config was written.
- Backup path if a file was modified.
- Manual snippet.
- Warnings for unsupported clients.

### `print_mcp_config`

Always prints the manual config snippet for a requested client shape.

## Job Storage

Default state directory:

```text
~/.translatorFork/mcp/
```

Inside it:

```text
daemon.json
jobs/
  <job_id>/
    job.json
    stdout.log
    stderr.log
    result.json
    command.json
```

`job.json` fields:

- `id`.
- `type`.
- `status`: `queued`, `running`, `succeeded`, `failed`, `cancelled`.
- `created_at`, `started_at`, `finished_at`.
- `project`.
- `epub`.
- `argv`.
- `pid`.
- `exit_code`.
- `result_path`.
- `stdout_path`.
- `stderr_path`.
- `error`.
- `children` for pipeline jobs.

## Data Flow

For a translation request:

1. Desktop AI client calls `start_translation`.
2. MCP stdio server validates arguments.
3. MCP stdio server ensures daemon is running.
4. Server sends a daemon request to enqueue a translation job.
5. Daemon writes `job.json`.
6. Daemon starts the CLI subprocess.
7. Worker writes stdout/stderr and CLI JSON result to job files.
8. Daemon updates job status.
9. The AI client can call `get_job_status` without receiving chapter bodies or full model outputs.

## Error Handling

- Invalid paths fail before enqueueing.
- Missing EPUB fails before enqueueing.
- Missing project folder is created only when the underlying CLI would create or use it safely.
- Missing API keys produce the same CLI error as normal headless runs, captured in `result.json` and `stderr.log`.
- Daemon startup failure returns a compact error with log path.
- Interrupted daemon startup marks previously running jobs as failed on the next boot.
- Config installer never edits a file without writing a backup first.

## Security And Privacy

- Do not expose API keys in MCP responses.
- Do not include full chapter text, full prompts, or full model responses in MCP tool output.
- Store logs on disk because local translator workflows already write project data locally.
- Restrict daemon control to the current user by filesystem permissions for sockets/tokens.
- Do not accept arbitrary shell strings. Build subprocess argv lists from validated tool arguments.
- Avoid executing user-provided commands through MCP.

## Client Compatibility

The server must remain a standard local stdio MCP server because that is the widest common format for desktop AI clients.

The installer supports:

- Codex: write or print the MCP server entry in the Codex config shape used on the current machine.
- Claude Desktop: write or print the `mcpServers` JSON shape.
- Antigravity: write when a supported config path and schema is detected; otherwise print a manual snippet.
- Generic: print a neutral stdio config with command, args, and environment.

If implementation cannot confidently identify a client config file, it must print instructions instead of guessing.

## Future GUI-Connected Agent Bridge

After the V1 daemon and stdio MCP server are stable, the GUI can grow a server control surface that uses the same daemon foundation but changes who drives the work.

The future flow:

1. The user opens GeminiTranslator and clicks `Start MCP server`.
2. The GUI starts or attaches to `translator-mcp-daemon`.
3. The GUI shows connection details: server status, transport, token state, connected clients, and active jobs.
4. The user asks a desktop AI app to connect to the translator server.
5. When the AI app connects, GeminiTranslator records the MCP client identity from the protocol handshake when available, or from an explicit registration tool when the client does not expose enough metadata.
6. GeminiTranslator shows the connected app name and waits for user approval before allowing project data access.
7. Translation, glossary, consistency, and pipeline jobs can run in either local-worker mode or external-agent mode.
8. In external-agent mode, the GUI/daemon creates granular work items, the AI client claims them through MCP tools, and the AI app may use its own subagents to complete them.
9. The AI client submits results back through MCP, and GeminiTranslator writes accepted task outputs to the normal project files.

This is feasible, but with one important boundary: MCP servers cannot force a desktop AI app to create subagents. GeminiTranslator can expose tasks, project context, and result submission tools. The connected AI app decides whether it uses its main agent, subagents, or another internal worker model.

### GUI Entry Points

Add a GUI service page or settings panel with:

- Start server.
- Stop server.
- Copy MCP config.
- Copy connection token or local URL when a direct local transport is available.
- Connected clients list.
- Per-client project permission state.
- Active delegated jobs.
- Recent agent logs.
- Revoke client access.

The GUI should use the same daemon state directory as the headless MCP implementation. It should not maintain a separate queue.

### Transport Shape

Keep the stdio server for clients such as Claude Desktop, Codex, and other desktop apps that launch MCP servers as subprocesses.

For the GUI-started mode, add a local daemon endpoint behind the stdio server:

```text
AI client -> stdio MCP shim -> translator-mcp-daemon <- GeminiTranslator GUI
```

If a client supports direct local HTTP MCP transport, it can connect directly:

```text
AI client -> local MCP endpoint -> translator-mcp-daemon <- GeminiTranslator GUI
```

The stdio shim remains the compatibility path, so the GUI-started server can still work with clients that only support subprocess MCP servers.

### Future Agent-Delegation MCP Tools

These tools are separate from the V1 `start_*` tools and are only needed once external-agent mode is implemented:

- `translator_register_client`: records a client name and capabilities if handshake metadata is insufficient.
- `translator_list_delegated_jobs`: lists jobs waiting for AI-client work.
- `translator_claim_task`: claims one granular task for the connected client.
- `translator_get_task_payload`: returns the minimal source payload needed for that task.
- `translator_submit_task_result`: submits translated, glossary, consistency, or repair output.
- `translator_report_task_progress`: appends progress text visible in the GUI.
- `translator_release_task`: releases a claimed task back to the queue.
- `translator_get_project_manifest`: returns high-level project metadata without chapter bodies.
- `translator_get_artifact`: returns requested project artifacts when permission allows it.

The task payloads must be small enough for the receiving AI app to handle in subagent contexts. Full books should be split by the existing task planning logic, not sent as one MCP response.

### Delegated Task Types

External-agent mode can support:

- Translate one planned chapter/chunk.
- Generate glossary entries for one planned chapter batch.
- Review/correct one glossary conflict group.
- Fix one untranslated residue batch.
- Check or fix one consistency chunk.

Each delegated task stores:

- Parent job id.
- Task id.
- Task type.
- Source chapter or batch identifiers.
- Claim owner.
- Claim timestamp.
- Input artifact path.
- Submitted result path.
- Status.
- Retry count.

### GUI Safety Rules

- The first connection from a client is read-only until the user grants project access.
- The GUI displays which client claimed which task.
- Revoking a client releases its claimed tasks.
- Submitted results are saved through the same project write paths as normal app work.
- The system may run structural checks needed to avoid corrupt files, but it does not ask the chat to judge translation quality.
- The GUI never exposes API keys to connected clients.

### Relationship To V1

V1 remains the required foundation:

- The daemon provides durable jobs.
- The stdio MCP server provides cross-client compatibility.
- Existing CLI-backed operations continue to work without an open GUI.

The GUI-connected agent bridge is an additive mode. It should not block the first daemon implementation, and it should not replace local-worker mode for users who want the translator app to run jobs with its configured providers.

## Testing

Unit tests:

- Job id generation.
- Job state transitions.
- Job persistence load/save.
- Command argv construction for each MCP tool.
- MCP response redaction of API keys and full text fields.
- Config snippet generation.
- Config backup and merge behavior with temporary files.

Integration tests without network:

- Start daemon.
- Enqueue a fake worker command.
- Read job status.
- Cancel a long fake worker.
- Recover after simulated daemon restart.
- Verify MCP server tools can call daemon methods through a test transport.

Existing CLI tests should be reused as proof that the worker commands build correct translator behavior. Full AI network calls are not required for the MCP test suite.

## Non-Goals For V1

- Do not rewrite the translation engine.
- Do not make MCP a model provider inside `config/api_providers.json`.
- Do not make the chat review or validate translation quality.
- Do not stream entire chapters or model responses back to the AI client.
- Do not support remote multi-user daemon access.
- Do not migrate every UI-only AI feature before the daemon foundation exists.

## Implementation Slices

1. Add job model, persistence, and subprocess worker runner.
2. Add daemon control API and lifecycle commands.
3. Add MCP stdio server tools that call the daemon.
4. Wire tools for existing CLI-backed operations.
5. Add client config snippet generation and safe installer.
6. Add full pipeline orchestration.
7. Add or explicitly stub glossary correction if it remains UI-only.
8. Add docs and verification commands.

## Acceptance Criteria

- A desktop MCP client can connect to `translator-mcp-server`.
- The client can start a translation job and receive a job id.
- The same or another MCP client can query the job status after enqueueing.
- Logs and result JSON are written to stable disk paths.
- The MCP response does not include full chapter bodies or API keys.
- At least one CLI-backed job type is covered by an integration test with a fake subprocess.
- Config installer can print snippets for Codex, Claude Desktop, Antigravity, and Generic.
- Config installer writes only when it recognizes the target file and creates a backup.
- Full pipeline creates a parent job and child job records.
- Existing CLI behavior continues to pass its current tests.
