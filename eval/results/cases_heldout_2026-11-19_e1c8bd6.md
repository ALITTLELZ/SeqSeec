# Evaluation: cases_heldout.jsonl

- Date: 2026-11-19  |  commit `e1c8bd6`  |  model `deepseek-flash` (api)
- Prompts: {'extract': 'extract_v1', 'infer': 'infer_v1', 'baseline': 'infer_noretrieval_v1'}
- Cases: 28 (26 in scope, 2 out of scope)
- Step 1 scope correct: 25/28
- Note: Run 2: after the registry revision and the label second check. Prompts unchanged (extract_v1, infer_v1, infer_noretrieval_v1). Not blind: labels were revised after seeing run 1.

| Arm | Accuracy | Wilson 95% | Confident wrong | Answered: right/total | Abstain recall | Abstain precision | Kit accuracy |
|---|---|---|---|---|---|---|---|
| rules | 19/26 | [0.539, 0.863] | 1 | 13/14 | 6/7 | 6/12 | 12/15 |
| rag | 21/26 | [0.621, 0.915] | 1 | 15/16 | 6/7 | 6/10 | 14/15 |
| norag | 17/26 | [0.462, 0.806] | 5 | 14/19 | 5/7 | 5/7 | n/a |

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
- R17 (unregistered_lookalike): expected UNSTRANDED, got INSUFFICIENT
- S07 (abbreviation): expected RF, got INSUFFICIENT

## norag: errors
- R07 (multiple_kits): expected AMBIGUOUS, got RF
- R09 (named_kit_typo): expected RF, got UNSTRANDED
- R12 (multiple_kits): expected AMBIGUOUS, got INSUFFICIENT
- R13 (unregistered_alternative): expected INSUFFICIENT, got RF
- R15 (unregistered_kit): expected RF, got INSUFFICIENT
- R16 (unregistered_kit): expected RF, got INSUFFICIENT
- S01 (named_kit): expected FR, got RF
- S02 (family_name): expected AMBIGUOUS, got INSUFFICIENT
- S09 (named_kit_version): expected FR, got RF
