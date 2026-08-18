# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository. Its content is kept in sync with `AGENTS.md` (the canonical instruction file for OpenCode sessions).

## Project Overview

Chinese-language Flask demo of a multi-agent AI novel-writing pipeline with two parallel flows. **Long-form**: premise → world-build → outline → per-chapter (write → consistency check → polish) with human confirmation between stages. **Short-form (短篇)**: framework → write → deslop-polish → review → precheck. All UI text and generated story content are in Chinese.

The system runs in two modes with no config change:
- **LLM mode**: calls an OpenAI-compatible chat API when `OPENAI_API_KEY` is set.
- **Demo mode**: when no key is present, `agents/base.py:call_llm()` silently returns hardcoded sample outputs via `_demo_fallback()` (registered per agent class via `register_demo()`; keyword matching in the prompt is a legacy fallback). This is by design — the full pipeline "works" without a real LLM, but generated content is always the same canned 苍澜大陆 / 寒江剑鸣 sample. Do not be surprised by this, and do not treat it as a bug.

> **Frozen convention (team agreement):** "Demo" = the fixed sample-output set used when there is no API key — `agents/base.py`'s `_demo_fallback()` / `DEMO_REGISTRY` / `DemoConfig` / `register_demo()`, all `DEMO_WORLD_BUILDING` / `DEMO_CHAPTER_OUTLINE` / `DEMO_NOVEL_CONTENT` / `DEMO_CHECK_RESULT` / `DEMO_POLISHED_CONTENT` / `DEMO_SUMMARY` canned responses, the per-agent `register_demo(...)` calls, and the demo-mode test (`tests/test_fixes.py::test_demo_mode_fallback`). **Do not modify, extend, or "fix" anything in that set — develop real features only.** "Demo" does NOT refer to the rest of the project.
>
> **Registered-demo additions (added later, still frozen):** `StoryReviewer` (review report dict), `ShortStory` (短篇 framework JSON), `ShortStoryWriter` (短篇 draft prose), `ContinuityAuditor` (审计报告 dict). Same rule: do not modify their content or registry keys; only new features may add further entries.

> **v0.4 连贯性强化（long-form）**: adds a **world-state ledger** (`core/world_state.py`), a **continuity contract** injected into every Writer call, **full-history semantic recall** (`_pick_summaries_full`) plus **bucketed history context** (`_build_history_buckets`), and a **periodic whole-book consistency audit** (`AuditAgent`, every `AUDIT_INTERVAL = 5` chapters). Details in the "World state ledger", "Bucketed context + full-history recall", and "Full-history consistency audit" sections below.

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

### Short-form flow (短篇)
Independent of the long-form state machine. `project.short_story` holds `framework` / `draft` / `polished` / `review_report` / `precheck`, driven by the synchronous endpoints `/api/short/architect` → `/api/short/write` → `/api/short/polish` → `/api/short/review` → `/api/short/precheck` (all POST, no SSE) plus `/api/short/status`. Genre-style knowledge is injected via `genre_style_rules()` / `short_story_rules()` from `core/skill_knowledge.py`.

### Skills (`core/skill_knowledge.py`, `core/skill_precheck.py`)
- Runtime loader injecting installed web-novel skills' `references/*.md` (from `~/.agents/skills`, overridable via `SKILLS_DIR`) into agent prompts. `get_knowledge(skill, path)` → `(text, source)`, `source ∈ {"file", "embedded"}`; missing dirs/files fall back to embedded `EMBEDDED_*` excerpts so the app works with no skills installed.
- Known skills: `story-review` (rubric/banned-words/anti-ai-writing + platform rubrics fanqie/qidian/zhihu), `story-long-write` (writing-craft / outline-structure-theory), `story-short-write` (short-craft / short-format / submission-craft / reversal-toolkit + `genre-styles/*.md`), `story-deslop` (reused via story-review's anti-ai rules). The genre-style map is `_GENRE_STYLE_MAP`; `genre_style_rules(genre)` and `short_story_rules(genre)` return the matching text.
- `core/skill_precheck.py` runs the **node precheck** (`run_precheck(text)`): loads `story-review`'s `scripts/precheck.mjs` via `node`, returns a normalized `{ok, findings, severity_map}`; degrades to an embedded pure-Python fallback if node/script is missing. Exposed as `/api/precheck/<num>` (chapters) and `/api/short/precheck` (short-form).

### Streaming / UI
- The UI runs pipeline steps over SSE: `/api/stream-world`, `/api/stream-outline`, `/api/stream-write/<num>`, `/api/stream-all` — consumed via `fetch` + `ReadableStream` in `static/js/app.js`. `GET /api/status` is fetched **once** on page load, not polled.
- The SSE endpoints re-implement the same pipeline logic inline **instead of calling `run_pipeline_step()`**. Keep them in sync when changing flow — don't assume `run_pipeline_step()` is the only path.
- The chapter viewer toggles draft / polished / check-report / review-report / precheck-report / audit-report views; `/api/review/<num>` and `/api/precheck/<num>` are POST endpoints, `/api/audit` is POST (trigger) + GET (last report). The short-story tab drives `/api/short-*` synchronously.

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
- `SummarizerAgent` → chapter summary
- `ReviewerAgent` → multi-perspective ReviewReport dict (pydantic-validated, repair-fed, reconciled)
- `ShortStoryAgent` → short-form 框架 JSON (via `run_framework()`) or full prose (via `run_write()`)
- `AuditAgent` → whole-book consistency AuditReport dict (via `run(chapters_text, world_state_text, bible_summary, issue_history_text, as_of_chapter)`)

Non-obvious contracts:
- JSON-returning agents (`WorldBuilder`, `OutlineArchitect`, `ChapterSummarizer`) strip Markdown code fences before `json.loads`, and on parse failure fall back to `{"raw_output": response, "parse_error": True}`. Downstream code must tolerate malformed agent output.
- **CheckerAgent (v0.3) is special-cased.** It does not use `_parse_json_response`: `run()` validates the LLM output against a pydantic `CheckReport` schema, feeds validation errors back to the model (up to `MAX_REPAIR_ATTEMPTS`), and raises `PlotCheckerError` if it never parses. The returned dict adds `needs_revision` (from `passed` + `overall_quality_score` vs `QUALITY_FLOOR`). Its demo fallback is a **dict**, so `_extract_json` passes dicts through. New inputs (`character_states`, `open_foreshadowing`, `prev_chapter_digest`, `issue_history`) come from `StoryStateTracker`.
- `WriterAgent` returns raw prose, not JSON; it uses delimiters `【写作笔记】` then `【正文】`. In rewrite mode `run()` requires `original_text` to be non-empty. Use `WriterAgent._extract_body()` to strip the writing notes.
- **ReviewerAgent** validates the LLM output against a pydantic `ReviewReport` schema, feeds validation errors back (up to `MAX_REPAIR_ATTEMPTS`), and reconciles findings. `run(chapter_text, chapter_num, rubric, rubric_source, ...)` — `chapter_num` must be truthy (positive int; pass `1` for single-shot short stories). Powers both `/api/review/<num>` and `/api/short/review`.
- **ShortStoryAgent** — `run_framework()` returns the 框架 JSON (title/logline/core_reversal+sections/characters/emotional_curve); `run_write()` returns prose with WriterAgent-style delimiters (`_extract_body()` strips notes). `_call_llm()` accepts an explicit `agent_name` to pick the right demo/model route; two registered demos: `ShortStory` (framework JSON) and `ShortStoryWriter` (draft prose).
- Each agent's JSON schema is defined inside its `system_prompt`. To change an agent's I/O format, update the prompt there **and** keep the parsing in `run()` plus downstream consumers (e.g. `_import_world_to_bible`, the tracker writeback in `_writeback_state` in app.py) in sync.

### Cross-chapter state (core/state.py)
`StoryStateTracker` is the cross-chapter ledger feeding the Checker: `build_checker_inputs()` produces the four Checker kwargs, and `app.py` calls `ingest_report()` after each chapter finalizes to update the open-foreshadowing ledger (【埋设】/【回收】), a rolling digest queue, and `issue_history`. It lives on the `NovelProject` singleton as `project.state_tracker`, is seeded from Story Bible characters at first check, and is persisted to `data/state.json`. `app.py` mirrors the tracker's foreshadowing ledger into the Story Bible — keep the two consistent with `build_context_for_chapter()`'s unresolved-foreshadowing reads.

### World state ledger (core/world_state.py, v0.4)
`WorldState` is the cross-chapter world snapshot feeding the Writer (via the continuity contract) and the Auditor. `apply_delta(chapter_num, delta)` merges per-chapter world deltas (characters/items/locations + `open_threads`) and records character `location_history` for teleportation detection; `set_foreshadowings(pending, as_of_chapter)` refreshes the unresolved-foreshadowing ledger from the Story Bible and computes each entry's `age` (chapters since planted).

The delta source is **`ChapterSummarizerAgent`**: the `ChapterSummary.world_state_delta` schema field was added in v0.4. `_to_delta_dict()` whitelists keys `{characters, items, locations, open_threads}`; the field defaults to `{}` so old/demo summaries stay valid, and `_merge_partials()` merges deltas across chunked summaries.

`app.py::_update_world_state(chapter_num, summary)` runs after summary extraction: it applies the delta, refreshes the foreshadowing ledger, advances `state_tracker.mark_chapter`, and persists. `_seed_tracker_characters()` also seeds initial character states into the ledger.

**Continuity contract**: `build_continuity_contract(world_state, unresolved_fs, current_arc, glossary)` renders a `=== 连贯性契约 ===` block (world state + aging foreshadowings + current arc + optional glossary). The header **MUST stay `=== ... ===`** — `_compress_context()` in `core/story_bible.py` splits sections on that pattern. The contract is injected as section 0 of `build_context_for_chapter()` and is kept even under compression.

### Bucketed context + full-history recall (core/story_bible.py, v0.4)
`build_context_for_chapter(chapter_num, chapter_outline, character_names, max_chars, index, world_state, current_arc)` now emits: section 0 连贯性契约, section 4 前情提要, section 4.5 历史脉络 (`_build_history_buckets`: older chapters aggregated per `SUMMARY_BUCKET_SIZE = 10`, capped at `MAX_HISTORY_BUCKETS = 5`), plus `current_arc` injection. When a vector index is enabled, the 前情提要 uses `_pick_summaries_full()` — full-history semantic recall over **all** `sum:*` docs, excluding recent ones already shown. `core/vector_index.py` `ENABLE_VECTOR` now defaults to **"on"** (auto-degrades if `sentence-transformers` is missing). Model download defaults to **ModelScope (魔搭)** via `snapshot_download` (see `MODEL_SOURCE`; falls back to Hugging Face when `modelscope` is missing or `MODEL_SOURCE=huggingface`).

### Full-history consistency audit (v0.4)
**`AuditAgent`** (name `ContinuityAuditor`) runs the whole-book consistency audit: inputs are sampled chapter text (head+tail 400 chars each, total capped ~12k chars), world-state text, a bible summary, and recent `issue_history`. It validates against a pydantic `AuditReport` (findings sorted S1>S2>S3>S4) with self-repair up to `MAX_REPAIR_ATTEMPTS = 2`; its demo is registered as `ContinuityAuditor`.

Triggered automatically every `AUDIT_INTERVAL = 5` chapters at the end of a chapter write via `_run_continuity_audit()`, and manually via `POST /api/audit` (GET returns the last report). **Report-only — never auto-rewrites**: findings tell the user which chapter to rewrite; the user picks and rewrites manually. The result lives in `project.audit_report` / `project.last_audited_chapter` and is exposed via `/api/status` (`audit` + `world_state` fields).

### Web UI (templates/, static/)
Single-page app: `templates/index.html`, dark theme in `static/css/style.css`, `static/js/app.js` wraps all `/api/*` calls and the SSE streams. Long-form chapter viewer toggles between draft / polished / check / review / precheck / audit views; a separate 短篇 tab drives the short-form pipeline. The sidebar shows a world-state summary (`world_state` counts) and audit summary (`audit` counts) from `/api/status`.

## Data flow notes

- After each step the StoryBible, outline, chapters, metadata, cross-chapter state, short-story state, and world-state ledger are written to `data/story_bible.json`, `data/outline.json`, `data/chapters.json`, `data/project_meta.json`, `data/state.json`, `data/short_story.json`, and `data/world_state.json`; `data/` is gitignored. `GET /api/export` writes and downloads `data/export.txt`.
- Chapter summaries are extracted after polishing in `_extract_and_update_summary()`, which delegates to the `ChapterSummarizerAgent` and falls back to a first-200-characters summary on failure. The agent computes `chapter_num` from code (not the model), so both live and Demo runs land on the correct chapter. After summary extraction, `_update_world_state()` folds the `world_state_delta` into the ledger.
- `_get_chapter_outline` matches chapters by integer `num`; keys of `project.chapters` are integers too. `_get_current_arc(chapter_num)` resolves the current volume's `arc_summary`/`climax` for the continuity contract.

## Style conventions

- UI copy, prompts, generated content, and most comments/docstrings are in Chinese — match that in new code.
- No comments should be added to code unless required; keep them light otherwise (existing code uses section banners with `# ===...`).