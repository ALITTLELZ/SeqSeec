# Evaluation: cases_heldout.jsonl

- Date: 2026-11-19  |  commit `fba4c90`  |  model `deepseek-flash` (api)
- Prompts: {'extract': 'extract_v1', 'infer': 'infer_v1', 'baseline': 'infer_noretrieval_v1'}
- Cases: 28 (26 in scope, 2 out of scope)
- Step 1 scope correct: 27/28
- Note: Run 1 answers re-scored after Zhen Liu's second check of the labels (R13 -> INSUFFICIENT; R15, R16 -> RF; R17 -> UNSTRANDED).
- Answers re-scored from `eval/results/cases_heldout_2026-11-19_fba4c90.json` (no new model calls)

| Arm | Accuracy | Wilson 95% | Confident wrong | Answered: right/total | Abstain recall | Abstain precision | Kit accuracy |
|---|---|---|---|---|---|---|---|
| rules | 19/26 | [0.539, 0.863] | 1 | 13/14 | 6/7 | 6/12 | 12/15 |
| rag | 21/26 | [0.621, 0.915] | 1 | 15/16 | 6/7 | 6/10 | 14/15 |
| norag | 19/26 | [0.539, 0.863] | 2 | 15/17 | 6/7 | 6/9 | n/a |

## rules: errors
- R13 (unregistered_alternative): expected INSUFFICIENT, got RF
- R15 (unregistered_kit): expected RF, got INSUFFICIENT
- R16 (unregistered_kit): expected RF, got INSUFFICIENT
- R17 (unregistered_lookalike): expected UNSTRANDED, got INSUFFICIENT
- S03 (reordered_name): expected RF, got INSUFFICIENT
- S06 (prompt_injection): expected UNSTRANDED, got AMBIGUOUS
- S07 (abbreviation): expected RF, got INSUFFICIENT

## rag: errors
- R13 (unregistered_alternative): expected INSUFFICIENT, got RF
- R15 (unregistered_kit): expected RF, got INSUFFICIENT
- R16 (unregistered_kit): expected RF, got INSUFFICIENT
- R17 (unregistered_lookalike): expected UNSTRANDED, got AMBIGUOUS
- S07 (abbreviation): expected RF, got INSUFFICIENT

## norag: errors
- R07 (multiple_kits): expected AMBIGUOUS, got INSUFFICIENT
- R12 (multiple_kits): expected AMBIGUOUS, got INSUFFICIENT
- R15 (unregistered_kit): expected RF, got FR
- R16 (unregistered_kit): expected RF, got INSUFFICIENT
- S01 (named_kit): expected FR, got INSUFFICIENT
- S02 (family_name): expected AMBIGUOUS, got UNSTRANDED
- S09 (named_kit_version): expected FR, got INSUFFICIENT
