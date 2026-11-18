# Changelog

Dated record of every change, its reason, and its owner. Newest first.

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
