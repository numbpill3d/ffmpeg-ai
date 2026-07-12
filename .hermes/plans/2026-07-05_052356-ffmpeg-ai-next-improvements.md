# ffmpeg-ai Next Improvements Plan

> For Hermes: use subagent-driven-development or strict TDD when executing these tasks.

Goal: make ffmpeg-ai more reliable, testable, and observable without changing its core UX.

Architecture: keep the current single-process CLI pipeline, but progressively separate orchestration from stage logic, add regression coverage around normalization/reporting, and expose machine-readable telemetry for every run.

Tech stack: Python 3.11, Typer, Rich, ffmpeg/ffprobe, pytest, asyncio.

---

## Current context

Already implemented in this pass:
- ffmpeg/ffprobe prerequisite checking
- thumbnail wrapping regression coverage
- `run_report.json` generation for successful and dry-run jobs
- repo ignore hygiene for nested `__pycache__`, `.pytest_cache`, `.poolside`

Still missing:
- tests for `_adapt_script()` normalization
- tests for dry-run and success-path report contents through `run_pipeline()`
- failure-path run reports
- async-native batch/auto execution without repeated `asyncio.run()`
- CLI/module decomposition

---

## Task 1: Cover script normalization with tests

Objective: lock down the current “repair malformed LLM output” behavior before refactoring it.

Files:
- Create: `tests/test_script_adaptation.py`
- Modify later: `src/ffmpeg_ai/pipeline.py`

Steps:
1. Write a failing test for string-valued `hook` and `cta` becoming dicts with `visual_prompts`.
2. Write a failing test for missing or empty `visual_prompts` on segments getting topic fallback.
3. Run targeted pytest commands until they fail for the expected reason.
4. Extract `_adapt_script()` into a top-level helper if needed for direct testing.
5. Re-run targeted tests, then full suite.

Validation:
- `pytest tests/test_script_adaptation.py -v`
- `pytest tests/ -q`

---

## Task 2: Add failure-path run reports

Objective: always emit `run_report.json`, even when the pipeline crashes mid-stage.

Files:
- Modify: `src/ffmpeg_ai/pipeline.py`
- Create: `tests/test_pipeline_failures.py`

Steps:
1. Write a failing test that monkeypatches a stage helper (for example `generate_script` or `encode_video`) to raise.
2. Assert `run_report.json` still exists and contains `status: failed` plus an error message.
3. Wrap the pipeline body in a narrow `try/except/finally` that finalizes the report before re-raising.
4. Re-run targeted tests, then full suite.

Validation:
- `pytest tests/test_pipeline_failures.py -v`
- `pytest tests/ -q`

---

## Task 3: Add a real dry-run integration test

Objective: verify the report and cache artifacts through an actual `run_pipeline()` call, not just helper tests.

Files:
- Create: `tests/test_pipeline_dry_run.py`
- Modify if needed: `src/ffmpeg_ai/pipeline.py`

Steps:
1. Write a failing async test using a temporary script JSON file.
2. Monkeypatch `_JOB_CACHE` to a temp dir.
3. Run `run_pipeline(..., script_path=..., dry_run=True)`.
4. Assert `run_report.json`, `metadata.json`, and `script.source` fields are correct.
5. Keep external dependencies mocked out except ffmpeg prerequisite checks if needed.

Validation:
- `pytest tests/test_pipeline_dry_run.py -v`
- `pytest tests/ -q`

---

## Task 4: Refactor batch/auto to one event loop

Objective: stop spawning repeated event loops and simplify provider-locking / async orchestration.

Files:
- Modify: `src/ffmpeg_ai/cli.py`
- Possibly modify: `src/ffmpeg_ai/ai/images.py`
- Create: `tests/test_cli_batch.py`

Steps:
1. Write failing tests for batch/auto using a shared async executor helper.
2. Add an internal async helper such as `_run_batch_topics(...)`.
3. Replace per-topic `asyncio.run(run_pipeline(...))` loops with one `asyncio.run(...)` wrapping the whole batch.
4. Simplify comments and loop-bound locking assumptions in `images.py` if they become obsolete.
5. Re-run full suite.

Validation:
- `pytest tests/test_cli_batch.py -v`
- `pytest tests/ -q`

---

## Task 5: Split CLI surface into submodules

Objective: reduce `cli.py` size and isolate command concerns.

Files:
- Create: `src/ffmpeg_ai/commands/generate.py`
- Create: `src/ffmpeg_ai/commands/batch.py`
- Create: `src/ffmpeg_ai/commands/auto.py`
- Modify: `src/ffmpeg_ai/cli.py`
- Create: command smoke tests under `tests/`

Steps:
1. Move pure helper functions first.
2. Move one command at a time with tests after each move.
3. Keep Typer registration behavior unchanged.
4. Re-run smoke tests after each extraction.

Validation:
- `pytest tests/ -q`
- `ruff check src tests`

---

## Risks / notes

- `run_pipeline()` is already large; use extraction plus tests, not blind edits.
- Batch/auto refactors touch concurrency and error handling; do them only after report coverage exists.
- Keep backward-compatible cache/job paths.
- Avoid refactoring command UX and pipeline semantics in the same change.

---

## Recommended execution order

1. Task 1: script normalization tests
2. Task 2: failure-path reporting
3. Task 3: dry-run integration test
4. Task 4: async batch/auto executor
5. Task 5: CLI decomposition
