# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository. Its content is kept in sync with `AGENTS.md` (the canonical instruction file for OpenCode sessions).

## Project Overview

Chinese-language Flask demo of a multi-agent AI novel-writing pipeline: premise → world-build → outline → per-chapter (write → consistency check → polish) with human confirmation between stages. All UI text and generated story content are in Chinese.

The system runs in two modes with no config change:
- **LLM mode**: calls an OpenAI-compatible chat API when `OPENAI_API_KEY` is set.
- **Demo mode**: when no key is present, `agents/base.py:call_llm()` silently returns hardcoded sample outputs via `_demo_fallback()` (registered per agent class via `register_demo()`; keyword matching in the prompt is a legacy fallback). This is by design — the full pipeline "works" without a real LLM, but generated content is always the same canned 苍澜大陆 / 寒江剑鸣 sample. Do not be surprised by this, and do not treat it as a bug.

> **Frozen convention (team agreement):** "Demo" = the fixed sample-output set used when there is no API key — `agents/base.py`'s `_demo_fallback()` / `DEMO_REGISTRY` / `DemoConfig` / `register_demo()`, all `DEMO_WORLD_BUILDING` / `DEMO_CHAPTER_OUTLINE` / `DEMO_NOVEL_CONTENT` / `DEMO_CHECK_RESULT` / `DEMO_POLISHED_CONTENT` / `DEMO_SUMMARY` canned responses, the per-agent `register_demo(...)` calls, and the demo-mode test (`tests/test_fixes.py::test_demo_mode_fallback`). **Do not modify, extend, or "fix" anything in that set — develop real features only.** "Demo" does NOT refer to the rest of the project.

## Commands

```bash
pip install -r requirements.txt   # install dependencies
python app.py                      # run the app → http://localhost:5000
```

- No linter/formatter/typecheck configured.
- Tests exist in `tests/test_fixes.py`: run `python -m pytest tests/ -v` or `python tests/test_fixes.py`. `pytest` is commented out of requirements.txt, so install it separately first. Most tests are meta-tests that read `app.py` source text, not behavioral assertions.
- `app.py` runs with `debug=True` on port 5000. **Must be started from the project root** — all data paths (`data/`, `data/story_bible.json`, etc.) are CWD-relative.
- `.env` **is** loaded: `app.py` calls `load_dotenv()` at import. Copy `env_template` → `.env`. Env keys: `OPENAI_API_KEY`, `OPENAI_BASE_URL` (default `https://api.openai.com/v1`), `LLM_MODEL`, `LLM_FALLBACK_MODEL`. `get_model_config()` in `agents/base.py` forces env-set models over the internal `MODEL_ROUTING` table (temperature/max_tokens come from the table).
- If an API call fails after retries, `call_llm()` also falls back to a demo response — a wrong key/base URL silently produces fake content. Verify the key or accept `_demo_fallback` output.

## Architecture

### Pipeline orchestration (app.py)
`app.py` is both the Flask app and the pipeline orchestrator. A single global `NovelProject` instance (`project`) holds all runtime state in memory — premise, StoryBible, outline, chapters, logs. There is no database; state is written to JSON files under `data/` after each step and **restored on startup** via `project.load_state()`.

- Every read/write of `project.*` state goes through `project._lock` (an `RLock`). Do the same in new code; otherwise the checked-in background threads will race.
- Each pipeline step (`run_pipeline_step()`) runs in a background `threading.Thread` guarded by `project.is_running`.
- **Human-in-the-loop**: the pipeline stops at `WORLD_BUILT` / `OUTLINE_GENERATED` / `CHAPTER_DONE` until `POST /api/confirm` advances it.
- Chapter writing is a retry loop: `Writer → Checker → Writer` (up to `MAX_RETRIES = 3`; severities `error`/`warning` are fed back as `revision_notes` until a check passes), then `Polisher`, then summary extraction.
- If you add a pipeline step, mirror this pattern: background thread + status message + `_log()` entries.

### Streaming / UI
- The UI runs pipeline steps over SSE: `/api/stream-world`, `/api/stream-outline`, `/api/stream-write/<num>`, `/api/stream-all` — consumed via `fetch` + `ReadableStream` in `static/js/app.js`. `GET /api/status` is fetched **once** on page load, not polled.
- The SSE endpoints re-implement the same pipeline logic inline **instead of calling `run_pipeline_step()`**. Keep them in sync when changing flow — don't assume `run_pipeline_step()` is the only path.

### The Story Bible (core/story_bible.py)
The central structured memory that guarantees consistency across chapters. Dataclasses: `Character`, `Location`, `Item`, `Foreshadowing`, `TimelineEvent`, `ChapterSummary`, held in dicts keyed by auto-generated `uuid` ids. `VersionedStoryBible` (subclass of `StoryBible`) supports `checkpoint()`/`rollback()` versioning across `MAX_VERSIONS`.

The key retrieval interface is `build_context_for_chapter()` — RAG-style context assembly (characters, unresolved foreshadowings, recent chapter summaries, timeline, world notes, style guide) injected into every `WriterAgent` call, compressing when over `MAX_CONTEXT_CHARS`. Keep its text-block format; other consumers (and tests) assume it.

### Agent system (agents/)
All agents subclass `BaseAgent` (agents/base.py) and override `system_prompt` and `run()`. Agents are not conversational — they take structured inputs and return structured output:

- `WorldBuilderAgent` → world JSON (world_name, geography, factions, characters, core_conflict, themes, style_notes)
- `OutlineAgent` → hierarchical outline JSON (volumes → chapters, each with scenes/conflict/hook/characters)
- `WriterAgent` → chapter prose (starts with `第X章 标题`; output is delimited `【写作笔记】` then `【正文】`) — the only agent that is **not** JSON
- `CheckerAgent` → check-report JSON (`passed`, `issues`, `overall_quality_score`, ...)
- `PolisherAgent` → polished prose

Non-obvious contracts:
- JSON-returning agents (`WorldBuilder`, `OutlineArchitect`, `ChapterSummarizer`) strip Markdown code fences before `json.loads`, and on parse failure fall back to `{"raw_output": response, "parse_error": True}`. Downstream code must tolerate malformed agent output.
- **CheckerAgent (v0.3) is special-cased.** It does not use `_parse_json_response`: `run()` validates the LLM output against a pydantic `CheckReport` schema, feeds validation errors back to the model (up to `MAX_REPAIR_ATTEMPTS`), and raises `PlotCheckerError` if it never parses. The returned dict adds `needs_revision` (from `passed` + `overall_quality_score` vs `QUALITY_FLOOR`). Its demo fallback is a **dict**, so `_extract_json` passes dicts through. New inputs (`character_states`, `open_foreshadowing`, `prev_chapter_digest`, `issue_history`) come from `StoryStateTracker`.
- `WriterAgent` returns raw prose, not JSON; it uses delimiters `【写作笔记】` then `【正文】`. In rewrite mode `run()` requires `original_text` to be non-empty. Use `WriterAgent._extract_body()` to strip the writing notes.
- Each agent's JSON schema is defined inside its `system_prompt`. To change an agent's I/O format, update the prompt there **and** keep the parsing in `run()` plus downstream consumers (e.g. `_import_world_to_bible`, the tracker writeback in `_writeback_state` in app.py) in sync.

### Cross-chapter state (core/state.py)
`StoryStateTracker` is the cross-chapter ledger feeding the Checker: `build_checker_inputs()` produces the four Checker kwargs, and `app.py` calls `ingest_report()` after each chapter finalizes to update the open-foreshadowing ledger (【埋设】/【回收】), a rolling digest queue, and `issue_history`. It lives on the `NovelProject` singleton as `project.state_tracker`, is seeded from Story Bible characters at first check, and is persisted to `data/state.json`. `app.py` mirrors the tracker's foreshadowing ledger into the Story Bible — keep the two consistent with `build_context_for_chapter()`'s unresolved-foreshadowing reads.

### Web UI (templates/, static/)
Single-page app: `templates/index.html`, dark theme in `static/css/style.css`, `static/js/app.js` wraps all `/api/*` calls and the SSE streams. The chapter viewer toggles between draft and polished text.

## Data flow notes

- After each step the StoryBible, outline, chapters, metadata, and cross-chapter state are written to `data/story_bible.json`, `data/outline.json`, `data/chapters.json`, `data/project_meta.json`, and `data/state.json`; `data/` is gitignored. `GET /api/export` writes and downloads `data/export.txt`.
- Chapter summaries are extracted after polishing in `_extract_and_update_summary()`, which delegates to the `ChapterSummarizerAgent` and falls back to a first-200-characters summary on failure. The agent computes `chapter_num` from code (not the model), so both live and Demo runs land on the correct chapter.
- `_get_chapter_outline` matches chapters by integer `num`; keys of `project.chapters` are integers too.

## Style conventions

- UI copy, prompts, generated content, and most comments/docstrings are in Chinese — match that in new code.
- No comments should be added to code unless required; keep them light otherwise (existing code uses section banners with `# ===...`).