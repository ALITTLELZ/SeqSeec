# SeqSeec

**Sequence Strandedness Extraction and Evaluation.** BIOINF 535 group project (Xiaomeng Du, Zhen Liu, Mariam Fateh), Fall 2026.

SeqSeec helps analysts with computational backgrounds work out how an RNA-seq library was made. It reads the lab notes, identifies the library-prep kit and the strandedness that kit should give, and cites the kit documentation. It then compares that expectation with a local check of the reads. Finally, it translates the result into the setting each downstream tool needs, such as `featureCounts -s` or Salmon `-l`. Reads never leave the machine.

## Status (v0.5, 2026-11-20)

| Step | Module | Status |
|---|---|---|
| 1 Notes → fields (LLM) | `seqseec/extract.py`, `prompts/extract_v1.md` | **working; live DeepSeek run OK on 2026-11-19**: quote-checked fields, scope decided by code, follow-up questions |
| 2–3 Notes → kit registry → expected orientation | `library/kit_registry.csv`, `seqseec/retrieve.py`, `infer.py`, `prompts/infer_v1.md` | **working**: 10 registry entries, each with a vendor source and verbatim quote; alias + keyword retrieval; LLM picks among candidates, code checks quotes and looks up the orientation; rules-only mode for `--llm none`; no-retrieval baseline for evaluation |
| 4 Local data check | `seqseec/datacheck.py` | **working**: wraps how_are_we_stranded_here; 7/7 smoke tests pass |
| 5–6 Reconcile, downstream settings | `seqseec/reconcile.py`, `settings.py` | **working**: decision table (incl. out-of-scope) and settings lookup; settings checked against official tool docs |
| 7 Explanation | `seqseec/explain.py` | not started |
| LLM payload gate + audit log (used by steps 1, 3, 7) | `seqseec/payload.py` | **working**: per-task allow-lists, read/FASTQ/API-key guards, append-only audit log |
| LLM client (used by steps 1, 3, 7) | `seqseec/llm.py` | **working**. Two modes: `api` (DeepSeek; live checks OK on 2026-11-19, see CHANGELOG) and `local` (Ollama on this machine; one real run on 2026-11-19 with `qwen3.5:2b`, not evaluated). JSON mode, accepts only `build_payload()` output, retries blank/invalid JSON, logs model ID and usage per call |
| One command | `seqseec/cli.py`, `pipeline.py` | **working**: `seqseec run` runs every step and prints one report; step 7 is a placeholder |
| Evaluation | `eval/` | **done for the prototype**: 28 held-out notes (17 real GEO); run 2: SeqSeec 21/26 correct, 1 confident wrong; same LLM without the registry 17/26, 5 confident wrong |
| Replay page | `demo/` | **working**: static replay of five saved runs + the evaluation, rebuilt by `demo/build_replay.py` |
| Spec sheet | `docs/SeqSeec_SpecSheet.md` (+ `.docx` for Google Docs) | prototype spec sheet, v0.5 |

## Setup

SeqSeec uses two conda environments:

**1. `seqseec-tools`: strandedness tools (kallisto 0.44.0, RSeQC, how_are_we_stranded_here).**

On Apple Silicon this environment runs under Rosetta, because bioconda ships kallisto 0.44 only for Intel and Linux:

```bash
CONDA_SUBDIR=osx-64 mamba env create -f envs/tools-osx64.yml
```

```bash
conda config --file "$(conda info --base)/envs/seqseec-tools/.condarc" --set subdir osx-64
```

On Linux or an HPC cluster, drop the `CONDA_SUBDIR=osx-64` prefix. See the comments in `envs/tools-osx64.yml` for why each version is pinned.

**2. App environment: the pipeline itself.** Any Python ≥ 3.10. From the repo root, install it in editable mode (needed, because `prompts/` sits next to the package). This gives the `seqseec` command:

```bash
pip install -e ".[test]"
```

**3. Choose an LLM mode (only needed to read notes; the tests never call an LLM).**

- `--llm api` (default): DeepSeek's hosted API. The notes leave the machine, so use public or synthetic notes only. Create a `.env` file in the repo root. It is git-ignored; never commit it.

  ```bash
  DEEPSEEK_API_KEY=sk-...
  # optional overrides
  # SEQSEEC_LLM_MODEL=deepseek-flash        # default; deepseek-v4-pro is the larger model
  # SEQSEEC_LLM_BASE_URL=https://api.deepseek.com
  ```

- `--llm local`: a model server on this machine, so nothing leaves the machine. No key is needed, and the URL must be localhost. With [Ollama](https://ollama.com): `ollama pull qwen3.5:2b`, then run with `--llm local`. Optional `.env` overrides: `SEQSEEC_LOCAL_MODEL` (default `qwen3.5:2b`) and `SEQSEEC_LOCAL_BASE_URL` (default `http://localhost:11434/v1`). Local requests send `reasoning_effort: "none"`, because thinking models otherwise use up the token budget.
- `--llm none`: no LLM. The notes are not read; give `--expected` if you know the kit's orientation.

## Usage

```bash
seqseec run --notes notes.txt --r1 R1.fq.gz --r2 R2.fq.gz --gtf genes.gtf --transcripts tx.fa
seqseec run --notes notes.txt --llm local --data-call RF     # reuse a data call from an earlier check
seqseec run --llm none --expected RF --data-call FR          # no LLM; prints CONFLICT + provisional settings
seqseec settings fr-firststrand --layout SE                  # just the settings table
```

`seqseec run --help` lists every option, grouped by step. `--format json` prints the full report and `--out report.json` saves it. The LLM logs go to `audit/`. A step that fails is reported, and the run continues: for example, an LLM error still gives settings from the reads. Exit codes: 0 report written; 1 report written but a step failed; 2 bad arguments or setup. `python -m seqseec ...` works without installing.

Steps 2–3 (kit lookup) and 7 (explanation) are not built yet. Until then, the kit's orientation comes only from `--expected`.

## Tests

```bash
python -m pytest -q tests
```

```bash
python tests/toy/run_smoke.py
```

- **`pytest`** covers every module, the `seqseec` command and the file-header convention, with fake LLM servers and a fake data check. It needs neither the tools environment nor an LLM.
- **`run_smoke.py`** simulates a toy genome and reads with known orientation: FR, RF, unstranded, R1/R2 swapped, and single-end. It then runs the real tool on each case and checks the calls. It needs `seqseec-tools` and takes about 2 minutes.

## Conventions

- **Branches:** short feature branches; another member reviews before merging to `main`.
- **File headers:** every script starts with this header, enforced by `tests/test_headers.py`:
  ```python
  # File: <path from repo root>
  # Version: X.Y.Z
  # Last modified: YYYY-MM-DD (author)
  # Change: <one line>
  ```
- **Changelog:** every change gets a dated entry in `CHANGELOG.md`.
- **Tags:** `v0.1-env` (tool environment validated), `eval-heldout-2026-11-19` (exact code of the first evaluation run). The current version is 0.5.0 (`pyproject.toml`), matching spec sheet v0.5.
- **Never commit:** reads (`*.fastq*`, `*.bam`), vendor PDFs, or `.env`. See `.gitignore`.

## Repository layout

```
seqseec/    pipeline modules; cli.py is the command, pipeline.py runs the steps
prompts/    versioned LLM prompts (prompt ID = file name)
scripts/    helper scripts, e.g. the live LLM check
envs/       conda environment files
tests/      unit tests; tests/toy/ holds the simulator and smoke test
docs/       prototype spec sheet (Markdown source + .docx for Google Docs)
```
