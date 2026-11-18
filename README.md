# SeqSeec

**Sequence Strandedness Extraction and Evaluation.** BIOINF 535 group project (Xiaomeng Du, Zhen Liu, Mariam Fateh), Fall 2026.

SeqSeec helps analysts with computational backgrounds work out how an RNA-seq library was made. It reads the lab notes, identifies the library-prep kit and the strandedness that kit should give, and cites the kit documentation. It then compares that expectation with a local check of the reads. Finally, it translates the result into the setting each downstream tool needs, such as `featureCounts -s` or Salmon `-l`. Reads never leave the machine.

The team plan is in [docs/SeqSeec_Prototype_Plan_EN.pdf](docs/SeqSeec_Prototype_Plan_EN.pdf).

## Status (v0.1-env, 2026-11-08)

| Step | Module | Status |
|---|---|---|
| 1–3 Notes → kit → expected orientation (LLM + RAG) | `seqseec/extract.py`, `retrieve.py`, `infer.py` | not started |
| 4 Local data check | `seqseec/datacheck.py` | **working**: wraps how_are_we_stranded_here; 7/7 smoke tests pass |
| 5–6 Reconcile, downstream settings | `seqseec/reconcile.py`, `settings.py` | **in review**: decision table and settings lookup with unit tests; tool settings still to be checked against official docs |
| 7 Explanation | `seqseec/explain.py` | not started |

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

**2. App environment: the pipeline itself.** It will be added with steps 1–3. For now any Python ≥ 3.10 with `pytest` runs the tests.

## Tests

```bash
python -m pytest -q tests
```

```bash
python tests/toy/run_smoke.py
```

- **`pytest`** covers the output parser, the threshold rules and the file-header convention. It does not need the tools environment.
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
- **Milestone tags:** `v0.1-env`, `v0.2-pipeline`, `v0.3-frozen`, `v1.0-submission`.
- **Never commit:** reads (`*.fastq*`, `*.bam`), vendor PDFs, or `.env`. See `.gitignore`.

## Repository layout

```
seqseec/    pipeline modules
envs/       conda environment files
tests/      unit tests; tests/toy/ holds the simulator and smoke test
docs/       team plan; spec sheet later
```
