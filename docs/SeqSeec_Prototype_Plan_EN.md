# SeqSeec Prototype Plan

**BIOINF 535 Group Project · Xiaomeng Du, Zhen Liu, Mariam Fateh · Team discussion draft, Nov 8, 2026 · §2–§5 and §8 updated Nov 19, 2026 to match the code**

**Due:** Prototype & Spec Sheet, Mon Nov 16, 2026 (50 pts). Presentation Dec 2 or 9. **Status (Sun Nov 8):** last week's meeting did not happen, and no code or test data exists yet. Work starts Mon Nov 9, which leaves **7 working days**.

## 1. What we are building

SeqSeec is the **reverse of last year's CmdSmith**.

| | CmdSmith | SeqSeec |
|---|---|---|
| User | Wet-lab researchers who lack command-line skills | Computational or statistical researchers who lack wet-lab background |
| Goes from → to | Scientific intent → runnable command | Lab notes + reads → what the experiment actually did and which downstream settings to use |
| Shared design ideas | RAG, forced JSON output, asks when information is missing, never auto-executes, human confirms | Same |

**Why use an LLM when `how_are_we_stranded_here` already detects strandedness?** (the instructor's question) The tool only reports what the reads look like. SeqSeec adds:
1. Kit, version and chemistry identification from messy notes, with cited documentation.
2. Detection of mismatches between documentation and data (sample swap, wrong notes, swapped R1/R2).
3. Translation of the result into each downstream tool's setting (a lookup table, not the LLM).
4. A plain explanation for computational readers, such as why dUTP chemistry gives RF.

## 2. Decisions

**Model: use an API, not a local model.**
- The test load is small (about 30 cases, a few hundred calls), so cost is low. An API needs no deployment, which leaves time for evaluation.
- We use the **DeepSeek API** (already available). The code keeps a thin LLM interface (`seqseec/llm.py`) so the model can be swapped later in one place. We freeze the model before formal evaluation and report its exact model ID and date.
  - The model name is set with `SEQSEEC_LLM_MODEL`. The default is `deepseek-flash`, which DeepSeek served with DeepSeek-V4.1-Flash-1017 as of Nov 19, 2026; `deepseek-v4-pro` is the larger option. The key is `DEEPSEEK_API_KEY` in `.env`.
  - Every call uses JSON mode and sends only a payload built by `payload.py`. Each attempt is logged to `audit/llm_calls.jsonl` with the requested and returned model IDs, the prompt ID and hash, the payload hash and token usage, which gives the model ID and date to report.
- With a third-party API, notes leave the machine. So the prototype uses **public or synthetic notes only**, and the spec sheet says so.
- A local model (Ollama) is future work only; with the shortened timeline we drop the comparison experiment.

**Claude Science: not part of the system.** It has no API and is chat-only. We can use it as a development Q&A helper, but not in the pipeline or the formal evaluation. Any fact from it must be verified against vendor documents before entering our registry.

**Redefining "sealed-box"** (instructor's request): reads never leave the machine; notes and numeric tool summaries do go to the LLM. We drop the "offline LLM" wording.

**Scope:** Illumina paired-end short-read bulk RNA-seq, human and mouse, 6–8 kits. Nanopore, PacBio and single-cell return "out of scope."

**Single-end:** the `check_strandedness` source code has a single-end mode when `--reads_2` is omitted, though the README does not document it. We test it on day 1. If it works, we add 1–2 single-end cases; if not, we report `unverified` and list it as a limitation.

**Deliverable:** a runnable local pipeline with real evaluation results, plus a static replay page for the working link and demo, clearly labeled as a replay of pre-computed runs.

## 3. Architecture

**Principle: the LLM only reads text and explains. Code makes the calls and sets the parameters. The LLM never touches raw data.**

```
Lab notes ─► 1 Field extraction (LLM→JSON) ─► 2 Retrieval (aliases+BM25+vectors, local)
                                                   │
                                                   ▼
                                     3 Document inference (LLM→JSON, citations required)
                                                   │  citation check; failure = insufficient info
                                                   ▼
FASTQ/BAM ─► 4 Local tools ─► numeric summary only ─► 5 Reconcile (decision table) ─► 6 Settings (lookup)
 (stay local)                                                        │
                                                                     ▼
                                               7 Explanation (LLM, JSON only) ─► Report, human confirms
```

- **Step 1 checks (in code, `seqseec/extract.py`, prompt `prompts/extract_v1.md`):** the LLM returns ten fields: kit name, version, vendor, chemistry, strand statement, RNA selection, read layout, platform, library type and organism. Each non-null field needs a quote that appears verbatim in the notes, or it is dropped and listed. Fixed-choice fields must use allowed values. Code, not the LLM, marks Nanopore, PacBio and single-cell as `out of scope` and writes the questions to ask when the kit, its version or the read layout is missing.
- **Step 3 checks (in code):** the chunk exists, the quote appears in that chunk, and the kit is in the registry. Any failure forces `Not sufficient information`.
- **Step 4 routes:** FASTQ goes to `check_strandedness`; BAM goes to RSeQC `infer_experiment.py`. The LLM has no shell access.
- **Isolation enforced by code:** an allow-list function (`seqseec/payload.py`) builds every LLM payload (notes, public document chunks, numeric summaries). Each task may use only its own parts: step 1 notes; step 3 notes, extracted fields and chunks; step 7 fields, inference, data summary, reconciliation result and chunks. Structured parts have key allow-lists, so an unexpected field such as a file path is refused. A run of 30 or more nucleotides, a FASTQ record or an API key blocks the whole payload; chunks from the curated library are exempt from the nucleotide-run check only, because kit manuals quote adapter sequences. All payloads, and every refusal (without the refused content), go to an append-only audit log, and a test asserts that no read sequences appear there.
- **Tool roles (peer review):** `how_are_we_stranded_here` calls RSeQC internally, so the two are **not independent evidence**. The real cross-check is **documentation vs. data**.
- **Stack:** Python, ChromaDB with local embeddings, rank_bm25, PyMuPDF, conda `environment.yml`.

## 4. Reference library

Vendor documents rarely state "RF" or "FR" directly, so we use two layers:
1. **`kit_registry.csv` (hand-curated):** kit → version → chemistry → orientation, with source URL, page, access date and license status. Two people cross-check each row.
2. **Vector store:** full kit manuals, with kit, version, vendor, date and source as chunk metadata.

**Candidate kits** (orientation filled in from documents only):
- Illumina: TruSeq Stranded mRNA, TruSeq Stranded Total RNA, TruSeq RNA v2, Illumina Stranded mRNA Prep
- NEB: NEBNext Ultra II Directional and non-directional
- Roche: KAPA mRNA HyperPrep, KAPA RNA HyperPrep
- Takara: SMARTer Stranded Total RNA-Seq Pico (check version differences)
- Lexogen: CORALL

**Near-identical kit names** (TruSeq Stranded mRNA vs. TruSeq RNA v2):
1. Match the alias table to get candidate kits.
2. Filter by metadata, then run hybrid retrieval.
3. The LLM picks from the candidates or answers "cannot determine."
4. If candidates differ in orientation and the notes cannot separate them, code returns `ambiguous` and asks the user. If the data check gives a direction, step 5 uses it to choose among the candidates (`DATA_ONLY`).

**Library updates:** new documents must include kit, version, date and source, and must pass a small regression set before activation. The repo stores links and a manifest, not vendor PDFs.

## 5. Deterministic rules

**Data call** (thresholds taken from the tool's source code):
- Dominant fraction `> 0.9`: stranded (FR or RF)
- Dominant fraction `< 0.6`: unstranded
- Otherwise: `inconclusive`
- Undetermined fraction `> 0.5`: data check invalid; check the reference, annotation or species

**Reconciliation — "who wins?"** Documents show what was *intended*; reads show what the files *are*. Neither silently overrides the other.

| Document | Data | State | Output |
|---|---|---|---|
| Out of scope | Anything | `OUT_OF_SCOPE` | No settings; say the protocol (e.g. Nanopore, PacBio, single-cell) is outside SeqSeec's scope |
| X | X | `CONCORDANT` | Give settings |
| X | Opposite direction | `CONFLICT` | **Provisional** settings from data; human review required; list likely causes (version, swapped R1/R2, file mix-up) |
| Stranded | Unstranded | `CONFLICT` | Same, and flag that the notes may be wrong |
| Unstranded | Stranded | `CONFLICT` | Same |
| X | Inconclusive | `INCONCLUSIVE` | No automatic settings; suggest contamination and quality checks |
| X | Invalid or not run | `UNVERIFIED` | **Provisional** settings from the documents; human review required; marked as not verified by data |
| Insufficient or ambiguous | A direction (FR, RF or unstranded) | `DATA_ONLY` | Give settings from data; state that the kit was not identified (if ambiguous: the data can choose among the candidate kits) |
| Insufficient or ambiguous | No direction (inconclusive, invalid or not run) | `INSUFFICIENT` | `Not sufficient information`; keep the data-check suggestions |

X is FR, RF or unstranded. An `ambiguous` result from step 3 is flagged in the output. Only `CONCORDANT` counts as the documents being confirmed by the data (`documents_confirmed_by_data`); `settings_basis` records whether settings came from documents, data or both.

**Settings table** (each item checked against the tool's official documentation or source code on Nov 18, 2026; sources are recorded in `seqseec/settings.py`):

| Orientation | RSeQC dominant (PE) | featureCounts | HISAT2 | Salmon | kallisto | HTSeq | STAR column |
|---|---|---|---|---|---|---|---|
| FR / fr-secondstrand | `1++,1--,2+-,2-+` | `-s 1` | `FR` | `ISF` | `--fr-stranded` | `yes` | 3 |
| RF / fr-firststrand | `1+-,1-+,2++,2--` | `-s 2` | `RF` | `ISR` | `--rf-stranded` | `reverse` | 4 |
| Unstranded | About even | `-s 0` | unset | `IU` | default | `no` | 2 |

Single-end reads differ only in RSeQC (`++,--` for FR, `+-,-+` for RF), HISAT2 (`F` / `R`) and Salmon (`SF` / `SR` / `U`). HTSeq defaults to `yes`, so unstranded data needs `no` set explicitly.

## 6. Testing and evaluation

**A. Notes-level (about 24 cases, text only)**
- Source: public GEO/SRA library construction text as a proxy for real notes, plus hand-written hard cases. Each case is labeled `real` or `synthetic`.
- Categories: explicit kit, name variants or look-alikes, chemistry only (such as dUTP), version-dependent, no information (should abstain), out of scope.
- Ground truth: two members label independently from kit documents **before** any model run, then resolve disagreements.
- Split: about 8 dev, about 16 held-out. The held-out set runs **once**, after prompts are frozen.

**B. Data-level (4–6 public datasets, subsampled to 200k reads)**
- Sources: ENCODE (`replicates.library.strand_specificity` confirmed to exist; the one record sampled had no kit information) and GEO datasets that name a kit.
- Engineered conflicts: correct reads with wrong notes; swapped R1/R2 to flip orientation.
- **No circular validation:** tool output is never the tool's own ground truth. This layer tests reconciliation and conflict detection. Real metadata-vs-tool disagreements are recorded, not corrected.

**Comparisons (held-out):** same model with vs. without retrieval, plus a qualitative comparison with `how_are_we_stranded_here` alone.

**Metrics:** kit and version accuracy, orientation accuracy by class, abstention precision and recall, retrieval hit@k, citation correctness, conflict-detection sensitivity and specificity, runtime, API cost. Report raw counts, confusion matrices and confidence intervals, given the small sample.

## 7. Team division and schedule (re-planned Nov 8)

### 7.1 Scope cuts for the lost two days
| Item | Original | Now |
|---|---|---|
| Kits | 8–12 | **6–8** |
| Notes-level cases | ~30 (10 dev / 20 held-out) | **~24 (8 / 16)** |
| Data-level datasets | 6–8 | **4–6** |
| RSeQC BAM route | Required | **Stretch goal**; main path is FASTQ only |
| Single-end test | Required | **Only if the environment goes smoothly**; otherwise marked `unverified` |
| Local model comparison | Optional | **Dropped**; future work only |

### 7.2 Roles (claim at kickoff)
Day-1 tasks in the three tracks do not depend on each other, so **everyone can start before we meet**.

| | **Track A: Knowledge base** | **Track B: Pipeline** | **Track C: Evaluation & docs** |
|---|---|---|---|
| **Owner** | ________ | ________ | ________ |
| **Reviewer** | ________ | ________ | ________ |
| **Owns** | Kit list, registry, aliases, manifest, vector store | Environment, code for steps 1–7, audit log, replay page, repo upkeep | Test cases, ground truth, evaluation runs, spec sheet |
| **Best fit** | Most comfortable reading kit manuals and library chemistry | Strongest in Python and environment setup; can lean on Claude Code | Strongest in statistics and technical writing |
| **Load** | ~3 focused days + labeling later | Heaviest, throughout | Light early, heaviest at the end |

### 7.3 Schedule
| Date | Track A | Track B | Track C | Milestone |
|---|---|---|---|---|
| **Sun Nov 8 (today)** | Share plan in group chat; claim tracks (poll is fine, no meeting needed) | | | |
| **Mon Nov 9** | 30-min kickoff; pick 6–8 kits; download documents | Init git repo; **validate environment**: conda, run `check_strandedness` | Fix test-case format; start collecting GEO cases | |
| **Tue Nov 10** | Send B a **3-kit registry stub** first, then continue | Steps 1–3 and citation checks (on the stub) | Keep collecting cases; download and subsample 4–6 datasets | `v0.1-env` |
| **Wed Nov 11** | Finish registry with two-person check; build vector store and alias table | Steps 4–6, audit log; pre-run tools and save JSON; **decide on tool fallback** | Label ground truth independently (A is second labeler); build conflict cases | `v0.2-pipeline` |
| **Thu Nov 12** | Add documents based on dev-set errors | Integrate step 7; run dev set end to end | Run dev set; compile error list | |
| **Fri Nov 13** | Spot-check citations in failures | Apply fixes, then **freeze prompts and model** | Prepare held-out evaluation script | `v0.3-frozen` |
| **Sat Nov 14** | Document data sources and licenses | Replay page and workflow diagram | **Run held-out set once**, with vs. without retrieval; draft spec sheet | |
| **Sun Nov 15** | Cross-read everything | Re-run from a clean environment | Finalize spec sheet | |
| **Mon Nov 16** | **Submit** | | | `v1.0-submission` |

### 7.4 How we work
- **Daily async stand-up:** each person posts three lines in the group chat (done yesterday / doing today / blocked on). No meeting needed.
- **Hand-offs** (where slips usually happen):
  - Nov 10: A → B, registry stub
  - Nov 11: C → B, labeled test cases
  - Nov 13: B → C, frozen version
- **Blind labeling:** A and C label ground truth together; the second labeler must not see model outputs before finishing.

### 7.5 Minimum viable submission
If we fall behind, Nov 16 must still include:
1. A complete spec sheet, with measured numbers in Testing and Validation
2. A runnable notes-level pipeline (steps 1, 2, 3, 5, 6, 7) evaluated on the held-out set
3. Tool results for 2–3 datasets (run locally, or pre-run on Linux/HPC as JSON) to demonstrate reconciliation and conflict detection
4. The replay page

**Fallback:** if the tools still do not run locally on Nov 11, switch at once to pre-running them on Linux or HPC and saving the JSON. The LLM and reconciliation work is unaffected.

## 8. Code version management (CS-lab style)

- **Git from day one.** Short feature branches; another member looks over the change before it merges to `main`. The team decides whether to create a GitHub repo and whether it is public.
- **Every script has a header** with its modification date and change:
  ```python
  # File: seqseec/reconcile.py
  # Version: 0.3.0
  # Last modified: 2026-11-10 (author initials)
  # Change: Added DATA_ONLY state to the decision table
  ```
- **`CHANGELOG.md`:** dated entries with the change, reason and owner, so we can trace development later.
- **Milestone tags:** see the schedule above.
- **Prompts are versioned too** (such as `prompts/infer_v2.md`), with changes logged. Each prompt file starts with an HTML-comment header (file, version, date, change) that is stripped before sending; the prompt ID is the file name.
- **Results are traceable:** each evaluation result records commit hash, prompt version, model ID and run date. `eval/results/` is append-only.
- **Automated check:** a test confirms that every script in `seqseec/` has the header.

**Repo layout (`Group Projects/SeqSeec/`):**
```
seqseec/    extract.py retrieve.py infer.py datacheck.py reconcile.py settings.py explain.py llm.py payload.py
prompts/    versioned system prompts
library/    kit_registry.csv  aliases.csv  manifest.csv  (no vendor PDFs)
eval/       cases_dev.jsonl  cases_heldout.jsonl  run_eval.py  results/
demo/       index.html  (replay page)
docs/       SpecSheet.docx  workflow diagram
tests/      decision table, settings, citation checks, payload isolation, file headers
environment.yml  README.md  CHANGELOG.md
```
API keys stay in `.env` and are not committed. FASTQ files stay out of the repo.

## 9. Spec sheet mapping

| Template item | Content |
|---|---|
| App Name and Link | SeqSeec; repo and replay page links (team confirms before anything goes public) |
| Description / Objective | Section 1; equity: helps small computational teams without a sequencing core or wet-lab collaborators |
| Primary Audience | Bioinformatics analysts with computational or statistical training and limited wet-lab background |
| Key Features | Document-vs-data reconciliation, traceable citations, enforced abstention, settings translation, reads stay local |
| Platform | Local Python pipeline + the exact model ID used |
| System Prompt | Full text from `prompts/` |
| Data Sources | **No model training or fine-tuning**; RAG document manifest and test-data accessions |
| Ethical Considerations | Honest data-flow statement; public or synthetic notes; bias toward major vendors; abstains when uncertain |
| Potential Challenges | Documents rarely state orientation, look-alike names, kallisto 0.44 dependency, few real notes |
| Known Limitations | Section 10 |
| Testing and Validation | Section 6 methods and **measured results** |
| Safety and Compliance | Research use only, not diagnostic; no certifications; no auto-execution; human confirmation; audit log; first step toward an FDA-style governance record |

## 10. Risks and limitations

- `how_are_we_stranded_here` expects kallisto 0.44.x, and its README warns that newer versions sometimes fail. Our development Mac (Apple Silicon) has no Docker or Singularity, and bioconda availability is **not yet confirmed**. Fallback: an osx-64 environment under Rosetta, or Linux/HPC.
- The prototype uses conda rather than the containers in the proposal; a Dockerfile is future work.
- The tool reads the **first N** reads, not a random sample, so position bias is possible.
- Annotation or chromosome-name mismatches can distort RSeQC results.
- We have no real lab notes. GEO text is a proxy and is usually tidier than real notes; the spec sheet will say so.
- Limited kit coverage, English only, and internet access needed for the API.

## 11. Proposal fixes (before the presentation)

- `FASTA` → `FASTQ`; state required inputs (transcriptome FASTA + GTF for `how_are_we_stranded_here`; BAM + BED for RSeQC)
- `strangeness` → `strandedness`; `Chatbox` → chatbot
- Resolve the "offline LLM" / "OpenAI" / "free local model" contradiction; replace the $0 budget with actual API cost
- Narrow ONT and PacBio scope; revise the "cross-validate" wording
- Move the evaluation plan into Methodology; add a workflow diagram

## 12. Verification

1. `pytest tests/`: every decision table row, settings table, citation checks (fake quotes must be rejected), no read sequences in the audit log, file headers present.
2. End-to-end on four cases: concordant; swapped R1/R2 → `CONFLICT`; no information → `INSUFFICIENT` or `DATA_ONLY`; look-alike kit → `ambiguous` or the correct version.
3. Re-run from a clean conda environment using only the README.
4. Trace every number on the replay page and spec sheet back to `eval/results/`.

## Questions for the meeting

1. Who owns each track, and who reviews each? What is each person's availability Nov 9–15?
2. Does anyone have Linux or HPC access as the fallback for the tools?
3. Can any member contribute de-identified real lab notes? (These could only be used after moving to a local model, or with approval to send them to an API.)
4. GitHub repo: private during development? Public at submission for the working link?
