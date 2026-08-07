# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Flask-based AI novel-writing demo ("小说写作 Agent") that simulates a professional author workflow via a multi-agent pipeline: **idea → world-building → outline → chapter writing → consistency check → polishing**. The UI and all generated story content are in Chinese.

The system runs in two modes with no config change:
- **LLM mode**: calls an OpenAI-compatible chat API when `OPENAI_API_KEY` is set.
- **Demo mode**: when no key is present, `agents/base.py:call_llm()` silently returns hardcoded sample outputs via `_demo_fallback()`, matched by keywords in the system prompt. This is by design — the full pipeline "works" without a real LLM, but generated content is always the same canned sample. Do not be surprised by this when running without a key.

## Commands

```bash
pip install -r requirements.txt   # install dependencies
python app.py                      # run the app → http://localhost:5000
```

- There is no test suite and no linter configured.
- `app.py` runs with `debug=True` on port 5000. It must be started from the project root — all data paths (`data/`, `data/story_bible.json`, etc.) are CWD-relative.
- LLM config is read from `os.environ`: `OPENAI_API_KEY`, `OPENAI_BASE_URL` (default `https://api.openai.com/v1`), `LLM_MODEL` (default `gpt-4o-mini`). `python-dotenv` is a dependency, but note the app code never calls `load_dotenv()`, so a `.env` file is not actually read.

## Architecture

### Pipeline orchestration (app.py)
`app.py` is both the Flask app and the pipeline orchestrator. A single global `NovelProject` instance (`project`) holds all runtime state in memory — premise, StoryBible, outline, chapters, logs. There is no database; state is written to JSON files under `data/` after each step but never reloaded on startup.

Each pipeline step (`run_pipeline_step()`) runs in a background `threading.Thread`:
- `world_build` → WorldBuilderAgent output imported into the StoryBible.
- `outline` → OutlineAgent produces the volume/chapter outline.
- `write_chapter` → per chapter: WriterAgent → CheckerAgent → PolisherAgent → extract summary & update the StoryBible.

The frontend polls `GET /api/status` every 3 seconds; `project.is_running` guards against concurrent steps. If you add a pipeline step, mirror this pattern: background thread + status message + `_log()` entries.

### The Story Bible (core/story_bible.py)
The central structured memory that guarantees consistency across chapters. Dataclasses: `Character`, `Location`, `Item`, `Foreshadowing`, `TimelineEvent`, `ChapterSummary`, held in dicts keyed by auto-generated `uuid` ids. Serialized via `to_dict()` / `to_json()` / `from_json()`.

The key retrieval interface is `build_context_for_chapter()` — RAG-style context assembly (characters, unresolved foreshadowings, recent chapter summaries, timeline, world notes, style guide) injected into every chapter the WriterAgent produces. Keep the text-block format it returns; other consumers assume it.

### Agent system (agents/)
All agents subclass `BaseAgent` (agents/base.py) and override `system_prompt` and `run()`. Agents are not conversational — they take structured inputs and return structured output:

- `WorldBuilderAgent` → world JSON (world_name, geography, factions, characters, core_conflict, themes, style_notes)
- `OutlineAgent` → hierarchical outline JSON (volumes → chapters, each with scenes/conflict/hook/characters)
- `WriterAgent` → chapter prose (starts with `第X章 标题`)
- `CheckerAgent` → check-report JSON (`passed`, `issues`, `overall_quality_score`, ...)
- `PolisherAgent` → polished prose

Non-obvious contract: every JSON-returning agent strips markdown code fences from the LLM response before `json.loads`, and on parse failure falls back to `{"raw_output": response, "parse_error": True}` (CheckerAgent also forces `passed: True` in that case). Downstream code must tolerate malformed agent output.

Each agent's JSON schema is defined inside its `system_prompt`. To change an agent's I/O format, update the prompt there **and** keep the parsing in `run()` plus downstream consumers (e.g. `_import_world_to_bible` in app.py) in sync.

### Web UI (templates/, static/)
Single-page app: `templates/index.html`, dark theme in `static/css/style.css`, `static/js/app.js` wraps all `/api/*` calls and polls `/api/status`. The chapter viewer toggles between draft and polished text.

## Data flow notes

- After each step the StoryBible and outline are written to `data/story_bible.json` and `data/outline.json`; `GET /api/export` writes and downloads `data/export.txt`.
- Chapter summaries are extracted after polishing in `_extract_and_update_summary()` (a raw `call_llm` call, not an Agent), falling back to a first-200-characters summary on failure.
- `_get_chapter_outline` matches chapters by integer `num`; keys of `project.chapters` are integers too.
