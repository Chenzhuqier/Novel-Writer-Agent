# AGENTS.md

Chinese-language Flask demo of a multi-agent AI novel-writing pipeline: two parallel flows. **Long-form**: premise → world-build → outline → per-chapter (write → consistency check → polish) with human confirmation between stages. **Short-form (短篇)**: framework → write → deslop-polish → review → precheck. All UI text and generated story content are in Chinese. There is an `AGENTS.md`/`CLAUDE.md` naming mixup in newer instructions on output markers; the authoritative repo content is in `CLAUDE.md` (similar content to this file).

> **v0.4 连贯性强化（long-form）**：在长篇写作中新增「世界状态账本 + 连续性契约 + 全史语义召回 + 周期性全量连贯性审计」，专门对抗长篇小说前文遗忘/前后不一致。详见下文「世界状态账本」与「全量连贯性审计」两节。

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
- State is persisted to `data/` (`story_bible.json`, `outline.json`, `chapters.json`, `project_meta.json`, `state.json`, `short_story.json`, `world_state.json`) after each step and **restored on startup** via `project.load_state()`. `data/` is gitignored.
- SSE streaming endpoints (`/api/stream-*`) re-implement the same pipeline logic instead of calling `run_pipeline_step()`. Keep them in sync when changing flow.
- `project.chapters` is keyed by int chapter num; outline chapters match by their `num` field (see `_get_chapter_outline`).
- The **short-form flow** is independent of the long-form state machine. `project.short_story` holds `framework` / `draft` / `polished` / `review_report` / `precheck`; it is driven by the synchronous endpoints `/api/short/architect` → `/api/short/write` → `/api/short/polish` → `/api/short/review` → `/api/short/precheck` (all POST, no SSE), plus `/api/short/status` for state. Genre-style knowledge is injected from `genre_style_rules()` (see below).

## Skills (`core/skill_knowledge.py`)

- Runtime loader that injects installed web-novel skills' `references/*.md` (from `~/.agents/skills`, overridable via `SKILLS_DIR`) into agent prompts. `get_knowledge(skill, path)` returns `(text, source)` with `source ∈ {"file", "embedded"}`; missing dirs/files fall back to embedded excerpts (`EMBEDDED_*`), so the app works with no skills installed.
- Known skills: `story-review` (rubric/banned-words/anti-ai-writing + platform rubrics fanqie/qidian/zhihu), `story-long-write` (writing-craft / outline-structure-theory), `story-short-write` (short-craft / short-format / submission-craft / reversal-toolkit + `genre-styles/*.md`), `story-deslop` (reused via story-review's anti-ai rules). The genre-style map is `_GENRE_STYLE_MAP` in this module; `genre_style_rules(genre)` and `short_story_rules(genre)` return the matching text.
- `core/skill_precheck.py` runs the **node precheck** (`run_precheck(text)`): loads `story-review`'s `scripts/precheck.mjs` via `node`, runs the reviewer's blocking/advisory checks, returns a normalized `{ok, findings, severity_map}`. If node or the script is missing it degrades to the embedded pure-Python fallback. Exposed as `/api/precheck/<num>` (chapters) and `/api/short/precheck` (short-form).

## Story Bible (`core/story_bible.py`)

- `VersionedStoryBible` (subclass of `StoryBible`) holds dicts of `Character`/`Location`/`Item`/`Foreshadowing` keyed by auto ids, plus `chapter_summaries`, `timeline`. Supports `checkpoint()`/`rollback()` versioning.
- `build_context_for_chapter()` is the RAG-style context injected into every `WriterAgent` call; it compresses when over `MAX_CONTEXT_CHARS`. Keep its text-block format; tests assert on it.

## Agents (`agents/`)

- JSON-producing agents (`WorldBuilder`, `OutlineArchitect`, `ChapterSummarizer`) parse via `BaseAgent._parse_json_response`, which strips markdown fences then `json.loads`. On parse failure they return `{"raw_output": ..., "parse_error": True}`. Downstream must tolerate malformed output.
- **CheckerAgent (v0.3) is special-cased.** It no longer uses `_parse_json_response`: `run()` validates the LLM output against a pydantic `CheckReport` schema, feeds validation errors back to the model (up to `MAX_REPAIR_ATTEMPTS`), and raises `PlotCheckerError` if it never parses. The returned dict adds `needs_revision` (computed from `passed` + `overall_quality_score` vs `QUALITY_FLOOR`). The demo fallback is a **dict** (not a JSON string) — `_extract_json` passes dicts through. Its new inputs (`character_states`, `open_foreshadowing`, `prev_chapter_digest`, `issue_history`) come from `StoryStateTracker` (see below), all optional.
- WriterAgent is the exception: it returns prose, not JSON, using delimiters `【写作笔记】` then `【正文】`. In rewrite mode `run()` requires `original_text` to be non-empty. Use `WriterAgent._extract_body()` to strip the writing notes.
- **ReviewerAgent** (`agents/reviewer_agent.py`) is the multi-perspective review agent. It validates the LLM output against a pydantic `ReviewReport` schema, feeds validation errors back to the model (up to `MAX_REPAIR_ATTEMPTS`), and reconciles findings. `run(chapter_text, chapter_num, rubric, rubric_source, ...)` — `chapter_num` must be truthy (a positive int; pass `1` for single-shot short stories). It powers both `/api/review/<num>` (long-form) and `/api/short/review` (short-form).
- **ShortStoryAgent** (`agents/short_story_agent.py`) drives the short-form flow. `run_framework()` returns the 框架 JSON (title/logline/core_reversal+sections/characters/emotional_curve); `run_write()` returns prose (delimiters like WriterAgent; `_extract_body()` strips notes). `_call_llm()` accepts an explicit `agent_name` to pick the right demo/model route. It has two registered demos: `ShortStory` (framework JSON) and `ShortStoryWriter` (draft prose).
- Each JSON schema is defined inside its `system_prompt`. To change an agent's I/O, update the prompt, the parsing in `run()`, **and** downstream consumers (e.g. `_import_world_to_bible`, the tracker writeback in `_writeback_state`, both in `app.py`) together.

## Cross-chapter state (`core/state.py`)

- `StoryStateTracker` is the cross-chapter ledger feeding the Checker. `build_checker_inputs()` returns the four Checker kwargs; after a chapter check finalizes, `app.py` calls `ingest_report()` to update the open-foreshadowing ledger (【埋设】/【回收】), the digest queue, and `issue_history`. It lives on the `NovelProject` singleton as `project.state_tracker`, is seeded from Story Bible characters at first check, and is persisted to `data/state.json` by `save_state()`/`load_state()`.
- `app.py` also mirrors the tracker's foreshadowing ledger into the Story Bible (`add_foreshadowing`/`resolve_foreshadowing`), and `build_context_for_chapter()` reads the Bible's unresolved foreshadowings — keep the two ledgers consistent.

## World state ledger (`core/world_state.py`, v0.4)

- `WorldState` is the cross-chapter world snapshot feeding the Writer (via `build_continuity_contract`) and the Auditor. `apply_delta(chapter_num, delta)` merges per-chapter world deltas (characters/items/locations + `open_threads`), tracking character `location_history` for teleportation detection. `set_foreshadowings(pending, as_of_chapter)` refreshes the unresolved-foreshadowing ledger from the Story Bible and computes each one's `age` (chapters since planted).
- The delta source is **`ChapterSummarizerAgent`**: `ChapterSummary.world_state_delta` (schema field added in v0.4). `_to_delta_dict()` whitelists keys `{characters, items, locations, open_threads}`; the field defaults to `{}` so old/demo summaries stay valid. The fallback coerces via `_to_delta_dict`, and `_merge_partials()` merges across chunked summaries.
- `app.py::_update_world_state(chapter_num, summary)` is called after summary extraction; it applies the delta, refreshes the foreshadowing ledger, advances `state_tracker.mark_chapter`, and persists. `_seed_tracker_characters()` also seeds initial character states into the ledger.
- **Continuity contract**: `build_continuity_contract(world_state, unresolved_fs, current_arc, glossary)` renders a `=== 连贯性契约 ===` block (world state + aging foreshadowings + current arc + optional glossary). **The header MUST stay `=== ... ===`** because `_compress_context()` in `core/story_bible.py` splits sections on that pattern. The contract is injected as the highest-priority section of `build_context_for_chapter()` (kept even under compression).

## Bucketed context + full-history recall (`core/story_bible.py`, v0.4)

- `build_context_for_chapter(chapter_num, chapter_outline, character_names, max_chars, index, world_state, current_arc)` adds: section 0 连贯性契约, section 4.5 历史脉络 (`_build_history_buckets`: chapters outside the recent window aggregated per `SUMMARY_BUCKET_SIZE=10`, capped at `MAX_HISTORY_BUCKETS=5`), and `current_arc` injection.
- When a vector index is enabled, the 前情提要 uses `_pick_summaries_full()` — full-history semantic recall over **all** `sum:*` docs (not just the recent window), excluding the recent ones already shown. `core/vector_index.py` `ENABLE_VECTOR` now defaults to **"on"** (auto-degrades if `sentence-transformers` is missing). Model download defaults to **ModelScope (魔搭)** via `snapshot_download` (see `MODEL_SOURCE`; falls back to Hugging Face when `modelscope` is missing or `MODEL_SOURCE=huggingface`).

## Full-history consistency audit (v0.4)

- **`AuditAgent`** (`agents/audit_agent.py`, name `ContinuityAuditor`): runs the whole-book consistency audit. Inputs: sampled chapter text (head+tail 400 chars each, capped ~12k chars), world-state text, bible summary, recent `issue_history`. Validates against pydantic `AuditReport` (findings sorted S1>S2>S3>S4), self-repairs up to `MAX_REPAIR_ATTEMPTS=2`. Its demo is registered as `ContinuityAuditor`.
- Triggered automatically every `AUDIT_INTERVAL = 5` chapters at the end of a chapter write (`_run_continuity_audit()`), and manually via `POST /api/audit` (GET returns the last report). **Report-only, never auto-rewrites**: findings tell the user which chapter to rewrite; the user picks and rewrites manually. Result is stored in `project.audit_report` / `project.last_audited_chapter`, exposed via `/api/status` (`audit` + `world_state` fields).

## Demo mode

When no key is available, `agents/base.py:_demo_fallback()` returns hardcoded sample canonical output (registered by class name via `register_demo()`; keyword matching in the prompt is a legacy fallback). A run without a key always produces the exact same 苍澜大陆 / 寒江剑鸣 content. Do not be surprised when this happens, and do not treat it as a bug.
> **Frozen convention (团队约定):** "Demo" = the fixed sample-output set used when there is no API key. This includes `agents/base.py`'s `_demo_fallback()` / `DEMO_REGISTRY` / `DemoConfig` / `register_demo()`, all `DEMO_WORLD_BUILDING` / `DEMO_CHAPTER_OUTLINE` / `DEMO_NOVEL_CONTENT` / `DEMO_CHECK_RESULT` / `DEMO_POLISHED_CONTENT` / `DEMO_SUMMARY` canned responses, the per-agent `register_demo(...)` calls, and the demo-mode test (`tests/test_fixes.py::test_demo_mode_fallback`). **Do not modify, extend, or "fix" anything in that set — develop real features only.** "Demo" does NOT refer to the rest of the project.
>
> **Registered-demo additions (added later, still frozen):** `StoryReviewer` (review report dict), `ShortStory` (短篇 framework JSON), `ShortStoryWriter` (短篇 draft prose), `ContinuityAuditor` (审计报告 dict). Same rule: do not modify their content or registry keys; only new features may add further entries.

## Style conventions

- UI copy, prompts, generated content, and most comments/docstrings are in Chinese — match that in new code.
- No comments should be added to code unless required; keep them light otherwise (existing code uses section banners with `# ===...`).