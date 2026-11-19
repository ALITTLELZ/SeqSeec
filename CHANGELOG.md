# Changelog

Dated record of every change, its reason, and its owner. Newest first.

## 2026-11-19 — one command, local LLM mode (XD, branch `feat/cli`)

### Added
- `seqseec/cli.py` and `seqseec/pipeline.py`: `seqseec run` runs every step once and prints one report, as text or `--format json`, and `--out` saves it.
  - **Step statuses:** each step records `ok`, `skipped`, `given`, `error` or `not_built`. A failed step does not stop the run; it counts as "no answer" in the decision table.
  - **Placeholders:** steps 2–3 (kit lookup) and 7 (explanation) are `not_built`. Until they exist, `--expected FR|RF|UNSTRANDED` supplies the documents' orientation.
  - **Reusing a data check:** `--data-call` reuses the result of an earlier data check instead of running the tools.
  - **Layout:** the reads' layout wins over `--layout`, which wins over the notes, which win over the PE default. A disagreement between notes and reads is reported as a warning.
  - **Exit codes:** 0 report written; 1 a step failed; 2 bad arguments or setup. API mode with no key stops before any step runs.
  - **Extending:** to add an option, add it to `pipeline.DEFAULTS` and its argument group in `cli.py`. A test checks that every `run` option has a default.
  - `seqseec settings <orientation> [--layout SE]` prints the settings table. `python -m seqseec` also works.
- `pyproject.toml`: `pip install -e .` provides the `seqseec` command. No new dependencies.
- **`--llm api|local|none`** (`llm.py` 0.2.0):
  - `local` talks to a model server on this machine through the same OpenAI-style API, by default Ollama at `http://localhost:11434/v1` with model `qwen3.5:2b`. No key is read or sent, and URLs that are not localhost are refused.
  - The call log records `mode`.
  - `none` skips the LLM, which gives the no-LLM baseline.
- `tests/test_pipeline.py`, `tests/test_cli.py`, and local-mode tests in `tests/test_llm.py`. Total 291 tests.
- README: install, LLM modes, usage. Plan §2: local mode, and "sealed box" with local mode. Plan §3: the command.

### Found in a real local run (laptop, Ollama 0.40.16, `qwen3.5:2b`, synthetic note)
- Without `reasoning_effort: "none"`, the Qwen3 "thinking" model spent 4 minutes reasoning and hit `max_tokens`, returning no JSON. With it, step 1 took about 28 s. Local mode now sends this field by default; extra fields cannot replace the model, messages or JSON mode.
- The run kept kit name, strand statement and platform, each with a verified quote. It **dropped `read_layout`**, because the model answered `"2x100"` instead of `PE`. Follow-up to decide: map `2xN` → PE and `1xN` → SE in code, or tighten the prompt.

### To do
- [ ] Check on Great Lakes: `pip install -e .`, then `python -m pytest -q tests` and `seqseec run --llm none --expected RF --data-call RF`.
- [ ] Key holder: also try `seqseec run --notes <synthetic note> --data-call RF` (api mode).

## 2026-11-19 — step 1: field extraction (XD, branch `feat/extract`)

### Added
- `prompts/extract_v1.md`: the first versioned prompt. It covers ten fields: kit name, version, vendor, chemistry, strand statement, RNA selection, read layout, platform, library type and organism. Each non-null field must carry a verbatim quote, the notes are treated as data, and the answer is a fixed JSON format with an example.
- `seqseec/extract.py`: `extract(notes)` runs `build_payload` → `call_llm` → `interpret()`. `interpret()` is pure code.
  - **Quote check:** a field whose quote does not appear verbatim in the notes is dropped and listed in `rejected`. Matching ignores case, spacing and curly quotes.
  - **Allowed values** are enforced for `read_layout`, `rna_selection` and `library_type`.
  - **Scope** is decided by code from the checked platform, library type and kit name: Nanopore, PacBio and single-cell are `OUT_OF_SCOPE`. Organisms other than human and mouse get a warning.
  - **Follow-up questions** are written by code when the kit, its version or the read layout is missing.
- `tests/test_extract.py`: quote checks, allowed values, scope, questions, the prompt file, and a check that the prompt's own example passes the code's checks. End-to-end runs use a fake API.
- Plan §3: step 1 checks bullet. Plan §8: prompt-file header convention. README: step 1 status row, and `prompts/` and `scripts/` in the layout.

- `scripts/check_llm_live.py --extract`: also runs step 1 live on the same synthetic note.

### Note
- Built on `feat/llm`. Not yet run against the live API.

### To do: step 1 live check (teammate who holds the DeepSeek API key)
- [ ] With the key in `.env`, run `python scripts/check_llm_live.py --extract` (two calls in total).
- [ ] Expected: `kit_name` "NEBNext Ultra II Directional RNA Library Prep Kit", `read_layout` "PE", `rna_selection` "polyA", `rejected` empty, scope `IN_SCOPE`, and one question asking for the kit version. Paste the output into the PR or group chat with the date. Anything in `rejected` means the prompt needs work.

## 2026-11-19 — LLM client (XD, branch `feat/llm`)

### Added
- `seqseec/llm.py`: `call_llm(built, system_prompt, prompt_id)`, the only code that talks to the LLM (plan §2, "thin interface").
  - **Payload gate:** sends only a `build_payload()` result and refuses one changed after it was built, by checking the SHA-256.
  - **JSON mode:** uses DeepSeek's `response_format` json_object. The system prompt must mention JSON, as the API requires, and a `prompt_id` is required so every call traces to a prompt version.
  - **Retries** once on blank or invalid JSON (a documented JSON-mode failure) and on HTTP 429/5xx. Output cut off at `max_tokens` is not retried.
  - **Call log:** one line per attempt in `audit/llm_calls.jsonl`, with task, prompt ID and hash, payload hash, requested and returned model IDs, token usage, time and output. The API key is never logged.
  - **Config:** `DEEPSEEK_API_KEY`, `SEQSEEC_LLM_MODEL` (default `deepseek-flash`) and `SEQSEEC_LLM_BASE_URL`, from the environment or `.env`. Standard library only, so no new dependency.
- `tests/test_llm.py`: fake transport, so no network or key is needed. Covers the request contents, refusals before any request, retries, the key never being logged, and config precedence.
- `scripts/check_llm_live.py`: one-call live check of the real API with a synthetic note; prints the requested and returned model IDs, token usage and output.
- README: setup step for `.env` and a status row. Plan §2: module name, current DeepSeek model names, and what each call logs.

### Note
- DeepSeek's model names changed since the plan was written (checked 2026-11-19 at api-docs.deepseek.com): `deepseek-flash` is served by DeepSeek-V4.1-Flash-1017, `deepseek-v4-pro` is the larger model, and `deepseek-v4-flash` is a legacy alias.
- Not yet run against the live API; that needs a key.

### To do: live API check (teammate who holds the DeepSeek API key)
- [ ] Put `DEEPSEEK_API_KEY=...` in `.env` in the repo root. It is git-ignored; never commit it.
- [ ] Run `python scripts/check_llm_live.py`. It sends one **synthetic** note, about one cent at most.
- [ ] Paste its `LIVE CHECK OK` lines (requested and returned model, tokens, output) into the PR or group chat with the date, and tick these boxes in a follow-up commit.
- If it fails, `audit/llm_calls.jsonl` has the error for each attempt; share that, but not the `.env` file.
- Built on `feat/payload` (PR #3).

## 2026-11-19 — LLM payload gate and audit log (XD, branch `feat/payload`)

### Added
- `seqseec/payload.py`: `build_payload(task, ...)` is the only way to build input for an LLM call (plan §3).
  - **Per-task parts:** extract takes notes; infer takes notes, fields and chunks; explain takes fields, inference, data_summary, reconcile and chunks.
  - **Key allow-lists** for the datacheck summary, the reconcile result and document chunks.
  - **Content guards:** a run of 30 or more nucleotides, a FASTQ record, an API key, or a string over 50,000 characters refuses the whole payload. Chunks are exempt from the nucleotide-run check only, because kit manuals quote adapters.
  - **Fails closed** and appends every built or refused payload to `audit/payload_audit.jsonl`. Refusals are logged without the refused content.
  - `check_audit_log()` re-scans a log.
- `tests/test_payload.py`: allowed and refused payloads, allow-lists kept in step with `datacheck` and `reconcile`, and the plan §12 check that no read sequences reach the audit log.
- `.gitignore`: `audit/`. README: status row for the payload gate.
- `docs/SeqSeec_Prototype_Plan_EN.md` §3: isolation bullet now states the concrete rules above.
- The reconcile allow-list uses `documents_confirmed_by_data`, so this needs PR #2 (merged 2026-11-19).

## 2026-11-19 — step 5 follow-ups from the PR #1 review (XD, branch `fix/reconcile-review-followups`)

Addresses the non-blocking points in ALITTLELZ's review of PR #1.

### Changed
- **New state `OUT_OF_SCOPE`** (review item 1). A document result of `OUT_OF_SCOPE`, for example Nanopore, PacBio or single-cell notes, now returns this state with no settings, whatever the data says. It used to raise `ValueError`.
- **`verified_by_data` replaced by `documents_confirmed_by_data`** (review item 2). The new field is True only for CONCORDANT. The old field was also True for CONFLICT and DATA_ONLY, which step 7 could have read as "verified". `settings_basis` still says where the settings come from. **This is an interface change:** code that reads `verified_by_data` must switch to the new field. No code in the repo reads it yet.
- **Input spelling** (review item 3). Spaces, underscores and hyphens are now interchangeable in document and data labels, so `not_sufficient_information`, `out-of-scope` and `not run` are all accepted.
- **AMBIGUOUS with a data call** (review item 3). The message now says the reads can be used to choose among the candidate kits, instead of "kit could not be identified".
- **INSUFFICIENT keeps the data checks** (review item 3). With an INCONCLUSIVE or INVALID data call, the result now includes the same contamination, quality and reference checks as the other states.
- README status for steps 5–6 updated from "in review" to "working".
- `docs/SeqSeec_Prototype_Plan_EN.md` brought in line with the code. §5 reconciliation table: added the OUT_OF_SCOPE row; ambiguous handling; UNVERIFIED gives provisional document settings; INSUFFICIENT keeps the data-check suggestions; note on `documents_confirmed_by_data`. Settings table: marked as checked against official docs, and added the single-end differences. §4 ambiguous step: the data call can choose among the candidates. **The PDF copy is not regenerated and still shows the Nov 8 text; the `.md` is current.**

## 2026-11-18 — steps 5–6: reconcile and settings (XD, branch `feat/reconcile-settings`)

### Added
- `seqseec/settings.py` (step 6): fixed lookup from orientation (FR / RF / UNSTRANDED) and layout (PE / SE) to featureCounts, HISAT2, Salmon, kallisto, HTSeq and STAR settings, plus the library-type name and the dominant RSeQC pattern. The patterns come from `datacheck.py`, so there is a single source. Single-end differs only for HISAT2 (`F`/`R`) and Salmon (`SF`/`SR`/`U`). Accepts `fr-firststrand`-style aliases.
- `seqseec/reconcile.py` (step 5): the plan §5 decision table with states CONCORDANT, CONFLICT, INCONCLUSIVE, UNVERIFIED, DATA_ONLY and INSUFFICIENT. On CONFLICT the settings follow the data, are marked provisional and require human review, and the result lists likely causes. Takes the datacheck result dict directly; its layout takes precedence.
- `tests/test_settings.py`, `tests/test_reconcile.py`: every cell of the 4 × 6 decision grid, the full settings table, aliases and bad input.

### Decisions (for team review)
- `AMBIGUOUS` from step 3 is treated as INSUFFICIENT and flagged (`document_ambiguous`).
- An INCONCLUSIVE data call with no document answer gives INSUFFICIENT, because neither side gives a direction.
- UNVERIFIED still returns the document's settings, marked provisional and not verified by data.

### Verified
- Every settings value was checked against the tool's official documentation or source and matched the plan §5 table; no changes were needed. Sources are recorded in `settings.SOURCES`: featureCounts (Subread usage text), HISAT2 manual, Salmon library-type docs, kallisto manual, HTSeq docs and the STAR manual.
- The kallisto manual says nothing about stranded single-end reads. The v0.44.0 source does not restrict `--fr-stranded`/`--rf-stranded` to paired-end, so the same flags are used for single-end.

## 2026-11-08 — v0.1-env (Track B)

### Added
- Repository skeleton: README, `.gitignore`, versioned file-header convention, and `tests/test_headers.py` to enforce it.
- Team plan (`docs/SeqSeec_Prototype_Plan_EN.md` / `.pdf`).
- `envs/tools-osx64.yml`: kallisto 0.44.0, RSeQC 5.0.x, how_are_we_stranded_here, under Rosetta on Apple Silicon.
- `seqseec/datacheck.py` (step 4): runs `check_strandedness`, parses the RSeQC fractions, and applies the tool's own thresholds (> 0.9 stranded, < 0.6 unstranded, otherwise inconclusive). SeqSeec adds an INVALID state when more than 50% of reads are unassignable. Returns numbers only, with no paths or sequences.
- `tests/toy/make_toy_data.py`: synthetic 12-gene genome with FR, RF and unstranded paired-end reads.
- `tests/toy/run_smoke.py`: 7 end-to-end cases (PE FR/RF/UN, PE RF with R1/R2 swapped, SE FR/RF/UN). **7/7 pass** in an environment rebuilt from the YAML file.

### Problems found and fixed during environment validation
1. **No kallisto 0.44 for Apple Silicon.** Bioconda's osx-arm64 builds start at 0.46.1, so the tools environment is osx-64 and runs under Rosetta.
2. **The how_are_we_stranded_here 1.0.1 release on bioconda is broken for us.** It (a) crashes with pandas 2.x and 1.5 (`read_csv(sep="\n")`), (b) fails on FASTA headers that have no description after the ID, and (c) has no single-end mode. All three are fixed on GitHub master commit `e6ce74d` (2022-07-05), which was never released. We pin that commit.
3. **Intel MKL warnings under Rosetta** were written into the tool's result file and broke its parser. Fixed by switching to OpenBLAS (`nomkl`).
4. **Spaces in paths break how_are_we_stranded_here**, because it builds shell commands from its arguments. Our own project path contains spaces. `datacheck.py` now symlinks inputs into a space-free temporary directory and caches the kallisto index in `~/.cache/seqseec/kallisto/`.

### Findings for the spec sheet / proposal
- Single-end data **can** be checked with the pinned commit, which answers the instructor's question. Verified so far on simulated data only.
- Swapping R1 and R2 flips the call from RF to FR, as expected. This confirms our plan to build engineered conflict cases this way.
- how_are_we_stranded_here calls RSeQC internally, so the two are not independent evidence. They are two entry points (FASTQ vs. BAM).
