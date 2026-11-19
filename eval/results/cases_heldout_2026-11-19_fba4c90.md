# Evaluation: cases_heldout.jsonl

- Date: 2026-11-19  |  commit `fba4c90`  |  model `deepseek-flash` (api)
- Prompts: {'extract': 'extract_v1', 'infer': 'infer_v1', 'baseline': 'infer_noretrieval_v1'}
- Cases: 28 (26 in scope, 2 out of scope)
- Step 1 scope correct: 27/28

| Arm | Accuracy | Wilson 95% | Confident wrong | Abstain recall | Abstain precision | Kit accuracy |
|---|---|---|---|---|---|---|
| rules | 22/26 | [0.665, 0.939] | 1 | 9/10 | 9/12 | 12/15 |
| rag | 23/26 | [0.71, 0.96] | 1 | 9/10 | 9/10 | 14/15 |
| norag | 18/26 | [0.5, 0.835] | 3 | 7/10 | 7/9 | n/a |

## rules: errors
- R13 (unregistered_alternative): expected AMBIGUOUS, got RF
- S03 (reordered_name): expected RF, got INSUFFICIENT
- S06 (prompt_injection): expected UNSTRANDED, got AMBIGUOUS
- S07 (abbreviation): expected RF, got INSUFFICIENT

## rag: errors
- R13 (unregistered_alternative): expected AMBIGUOUS, got RF
- R17 (unregistered_lookalike): expected INSUFFICIENT, got AMBIGUOUS
- S07 (abbreviation): expected RF, got INSUFFICIENT

## norag: errors
- R07 (multiple_kits): expected AMBIGUOUS, got INSUFFICIENT
- R12 (multiple_kits): expected AMBIGUOUS, got INSUFFICIENT
- R13 (unregistered_alternative): expected AMBIGUOUS, got INSUFFICIENT
- R15 (unregistered_kit): expected INSUFFICIENT, got FR
- R17 (unregistered_lookalike): expected INSUFFICIENT, got UNSTRANDED
- S01 (named_kit): expected FR, got INSUFFICIENT
- S02 (family_name): expected AMBIGUOUS, got UNSTRANDED
- S09 (named_kit_version): expected FR, got INSUFFICIENT
