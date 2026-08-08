# AGENTS.md

Chinese-language Flask demo of a multi-agent AI novel-writing pipeline: premise → world-build → outline → per-chapter (write → consistency check → polish) with human confirmation between stages. All UI text and generated story content are in Chinese. There is an `AGENTS.md`/`CLAUDE.md` naming mixup in newer instructions on output markers; the authoritative repo content is in `CLAUDE.md` (similar content to this file).

## Commands

- `pip install -r requirements.txt`
- `python app.py` — serves `http://localhost:5000` with `debug=True`. **Must run from the project root**: all `data/` paths are CWD-relative.
- No linter/formatter/typecheck configured.
- Tests exist in `tests/test_fixes.py`: run `python -m pytest tests/ -v` or `python tests/test_fixes.py`. `pytest` is commented out of requirements.txt, so install it separately first. Most tests are meta-tests that read `app.py` source text, not behavioral assertions.

## LLM modes and config

- `.env` **is** loaded: `app.py` calls `load_dotenv()` at import. Copy `env_template` → `.env`, or set env vars directly.
- Env keys: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL`, `LLM_FALLBACK_MODEL`. `get_model_config()` in `agents/base.py` forces env-set models over its internal `MODEL_ROUTING` table (temperature/max_tokens come from the table).
- **Without `OPENAI_API_KEY`, every agent call returns a canned demo response.** This is by design (see Demo mode below). Don't "fix" it.
- If the API call fails after retries, `call_llm()` also falls back to a demo response — so a wrong key/base URL silently produces fake content. Verify the key or stick to `_demo_fallback` behavior.

## Architecture

- `app.py` is both the Flask app and pipeline orchestrator. A global `NovelProject` singleton (`project`) holds all state in memory; each pipeline step runs in a background `threading.Thread` guarded by `project.is_running`. The UI runs steps over SSE (`/api/stream-*`, `fetch` + `ReadableStream` in `static/js/app.js`); `GET /api/status` is fetched once on page load, not polled. The stream endpoints emit their own `raw_output`/SSE events, so don't assume `run_pipeline_step()` is the only path.
- Every read/write of `project.*` state goes through `project._lock` (an RLock). Do the same in new code; otherwise the checked-in threads will race.
- The pipeline has a human-in-the-loop state machine: it stops at `WORLD_BUILT` / `OUTLINE_GENERATED` / `CHAPTER_DONE` until `POST /api/confirm` advances it. Chapter writing is a retry loop `Writer → Checker → Writer` (up to `MAX_RETRIES = 3`, issue severities `error`/`warning` fed back as `revision_notes`, until a check `passed`), then `Polisher`, then summary extraction.
- State is persisted to `data/` (`story_bible.json`, `outline.json`, `chapters.json`, `project_meta.json`, `state.json`) after each step and **restored on startup** via `project.load_state()`. `data/` is gitignored.
- SSE streaming endpoints (`/api/stream-*`) re-implement the same pipeline logic instead of calling `run_pipeline_step()`. Keep them in sync when changing flow.
- `project.chapters` is keyed by int chapter num; outline chapters match by their `num` field (see `_get_chapter_outline`).

## Story Bible (`core/story_bible.py`)

- `VersionedStoryBible` (subclass of `StoryBible`) holds dicts of `Character`/`Location`/`Item`/`Foreshadowing` keyed by auto ids, plus `chapter_summaries`, `timeline`. Supports `checkpoint()`/`rollback()` versioning.
- `build_context_for_chapter()` is the RAG-style context injected into every `WriterAgent` call; it compresses when over `MAX_CONTEXT_CHARS`. Keep its text-block format; tests assert on it.

## Agents (`agents/`)

- JSON-producing agents (`WorldBuilder`, `OutlineArchitect`, `ChapterSummarizer`) parse via `BaseAgent._parse_json_response`, which strips markdown fences then `json.loads`. On parse failure they return `{"raw_output": ..., "parse_error": True}`. Downstream must tolerate malformed output.
- **CheckerAgent (v0.3) is special-cased.** It no longer uses `_parse_json_response`: `run()` validates the LLM output against a pydantic `CheckReport` schema, feeds validation errors back to the model (up to `MAX_REPAIR_ATTEMPTS`), and raises `PlotCheckerError` if it never parses. The returned dict adds `needs_revision` (computed from `passed` + `overall_quality_score` vs `QUALITY_FLOOR`). The demo fallback is a **dict** (not a JSON string) — `_extract_json` passes dicts through. Its new inputs (`character_states`, `open_foreshadowing`, `prev_chapter_digest`, `issue_history`) come from `StoryStateTracker` (see below), all optional.
- WriterAgent is the exception: it returns prose, not JSON, using delimiters `【写作笔记】` then `【正文】`. In rewrite mode `run()` requires `original_text` to be non-empty. Use `WriterAgent._extract_body()` to strip the writing notes.
- Each JSON schema is defined inside its `system_prompt`. To change an agent's I/O, update the prompt, the parsing in `run()`, **and** downstream consumers (e.g. `_import_world_to_bible`, the tracker writeback in `_writeback_state`, both in `app.py`) together.

## Cross-chapter state (`core/state.py`)

- `StoryStateTracker` is the cross-chapter ledger feeding the Checker. `build_checker_inputs()` returns the four Checker kwargs; after a chapter check finalizes, `app.py` calls `ingest_report()` to update the open-foreshadowing ledger (【埋设】/【回收】), the digest queue, and `issue_history`. It lives on the `NovelProject` singleton as `project.state_tracker`, is seeded from Story Bible characters at first check, and is persisted to `data/state.json` by `save_state()`/`load_state()`.
- `app.py` also mirrors the tracker's foreshadowing ledger into the Story Bible (`add_foreshadowing`/`resolve_foreshadowing`), and `build_context_for_chapter()` reads the Bible's unresolved foreshadowings — keep the two ledgers consistent.

## Demo mode

When no key is available, `agents/base.py:_demo_fallback()` returns hardcoded sample canonical output (registered by class name via `register_demo()`; keyword matching in the prompt is a legacy fallback). A run without a key always produces the exact same 苍澜大陆 / 寒江剑鸣 content. Do not be surprised when this happens, and do not treat it as a bug.

> **Frozen convention (团队约定):** "Demo" = the fixed sample-output set used when there is no API key. This includes `agents/base.py`'s `_demo_fallback()` / `DEMO_REGISTRY` / `DemoConfig` / `register_demo()`, all `DEMO_WORLD_BUILDING` / `DEMO_CHAPTER_OUTLINE` / `DEMO_NOVEL_CONTENT` / `DEMO_CHECK_RESULT` / `DEMO_POLISHED_CONTENT` / `DEMO_SUMMARY` canned responses, the per-agent `register_demo(...)` calls, and the demo-mode test (`tests/test_fixes.py::test_demo_mode_fallback`). **Do not modify, extend, or "fix" anything in that set — develop real features only.** "Demo" does NOT refer to the rest of the project.

## Style conventions

- UI copy, prompts, generated content, and most comments/docstrings are in Chinese — match that in new code.
- No comments should be added to code unless required; keep them light otherwise (existing code uses section banners with `# ===...`).