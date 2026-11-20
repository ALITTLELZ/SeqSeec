# File: eval/run_eval.py
# Version: 0.2.0
# Last modified: 2026-11-19 (Track B)
# Change: Add answered-with-a-direction metric, --rescore (new labels, no model calls) and --note.
"""Run the notes-level evaluation (plan §6A) and write an append-only result file.

For each case: step 1 extract (LLM) -> fields and scope; then three ways to get the
documents' orientation:
  rules   infer_rules        no LLM: registry aliases only
  rag     infer              LLM chooses among retrieved registry entries; code checks quotes
  norag   infer_without_retrieval  same model, no documents (the proposal's baseline)

Scoring (cases expected OUT_OF_SCOPE are scored on step 1 scope only):
  accuracy               answer == expected label (FR, RF, UNSTRANDED, AMBIGUOUS, INSUFFICIENT)
  confident_wrong        answered FR/RF/UNSTRANDED but the expected label differs (the unsafe error)
  abstain recall/precision  "no single answer" (AMBIGUOUS or INSUFFICIENT) vs expected
  kit accuracy           chosen kit == expected kit, over cases with an expected kit
  answered / right       how many cases got a direction (FR/RF/UNSTRANDED) and how many of those were right
Accuracy comes with a Wilson 95% interval; with this few cases, read the raw counts.

Usage (repo root; needs DEEPSEEK_API_KEY in .env; costs a few cents):
  python eval/run_eval.py eval/cases_heldout.jsonl [--workers 4] [--note "..."]
  python eval/run_eval.py eval/cases_heldout.jsonl --rescore eval/results/<earlier>.json --note "..."
      (re-score saved answers against the current labels; no model calls)
Writes eval/results/<casefile>_<date>_<commit>.json (+ .md summary). Never overwrites.
"""
import argparse
import collections
import concurrent.futures
import datetime
import json
import math
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from seqseec.extract import PROMPT_ID as EXTRACT_PROMPT, extract  # noqa: E402
from seqseec.infer import BASELINE_PROMPT_ID, PROMPT_ID as INFER_PROMPT, infer, infer_rules, infer_without_retrieval  # noqa: E402
from seqseec.llm import LLMError, get_config  # noqa: E402

ARMS = ("rules", "rag", "norag")
LABELS = ("FR", "RF", "UNSTRANDED", "AMBIGUOUS", "INSUFFICIENT")
DIRECTIONS = ("FR", "RF", "UNSTRANDED")


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 3), round(c + h, 3)]


def run_case(case, config, audit_dir):
    logs = {"audit_log": os.path.join(audit_dir, "payload_audit.jsonl"),
            "call_log": os.path.join(audit_dir, "llm_calls.jsonl")}
    row = {"id": case["id"], "errors": {}}
    t0 = time.monotonic()
    try:
        ex = extract(case["notes"], config=config, max_tokens=4000, **logs)
        row["scope"], fields = ex["scope"], ex["fields"]
        row["extract_rejected"] = ex["rejected"]
    except (LLMError, ValueError) as err:
        row["scope"], fields = None, {}
        row["errors"]["extract"] = f"{type(err).__name__}: {err}"
    r = infer_rules(case["notes"], fields)
    row["rules"] = {"answer": r["document_orientation"], "kit_id": r["kit_id"]}
    try:
        g = infer(case["notes"], fields, config=config, **logs)
        row["rag"] = {"answer": g["document_orientation"], "kit_id": g["kit_id"], "rejected": g["rejected"],
                      "retrieval_method": g["retrieval_method"], "notes_quote": g["notes_quote"],
                      "citation": g["citation"], "reason": g["reason"]}
    except (LLMError, ValueError) as err:
        row["rag"] = {"answer": "INSUFFICIENT", "kit_id": None}
        row["errors"]["rag"] = f"{type(err).__name__}: {err}"
    try:
        b = infer_without_retrieval(case["notes"], fields, config=config, **logs)
        row["norag"] = {"answer": b["document_orientation"], "kit_guess": b["kit"], "reason": b["reason"]}
    except (LLMError, ValueError) as err:
        row["norag"] = {"answer": "INSUFFICIENT", "kit_guess": None}
        row["errors"]["norag"] = f"{type(err).__name__}: {err}"
    row["seconds"] = round(time.monotonic() - t0, 1)
    return row


def score(cases, rows):
    by_id = {r["id"]: r for r in rows}
    in_scope = [c for c in cases if c["expected_scope"] == "IN_SCOPE"]
    oos = [c for c in cases if c["expected_scope"] == "OUT_OF_SCOPE"]
    metrics = {"n_cases": len(cases), "n_in_scope": len(in_scope), "n_out_of_scope": len(oos),
               "scope_correct": sum(by_id[c["id"]]["scope"] == c["expected_scope"] for c in cases),
               "arms": {}}
    for arm in ARMS:
        correct = confident_wrong = answered = answered_right = 0
        abst_tp = abst_fp = abst_fn = 0
        kit_n = kit_ok = 0
        confusion = collections.defaultdict(collections.Counter)
        per_cat = collections.defaultdict(lambda: [0, 0])
        wrong = []
        for c in in_scope:
            ans, exp = by_id[c["id"]][arm]["answer"], c["expected_document"]
            confusion[exp][ans] += 1
            ok = ans == exp
            correct += ok
            per_cat[c["category"]][0] += ok
            per_cat[c["category"]][1] += 1
            if ans in DIRECTIONS:
                answered += 1
                answered_right += ok
                confident_wrong += not ok
            exp_abst, ans_abst = exp not in DIRECTIONS, ans not in DIRECTIONS
            abst_tp += exp_abst and ans_abst
            abst_fp += ans_abst and not exp_abst
            abst_fn += exp_abst and not ans_abst
            if c.get("expected_kit_id") and arm != "norag":
                kit_n += 1
                kit_ok += by_id[c["id"]][arm].get("kit_id") == c["expected_kit_id"]
            if not ok:
                wrong.append({"id": c["id"], "expected": exp, "answer": ans, "category": c["category"]})
        n = len(in_scope)
        metrics["arms"][arm] = {
            "accuracy": [correct, n], "accuracy_wilson95": wilson(correct, n),
            "confident_wrong": confident_wrong, "answered_right": [answered_right, answered],
            "abstain_recall": [abst_tp, abst_tp + abst_fn], "abstain_precision": [abst_tp, abst_tp + abst_fp],
            "kit_accuracy": [kit_ok, kit_n] if arm != "norag" else None,
            "confusion": {e: dict(confusion[e]) for e in LABELS if e in confusion},
            "per_category": {k: v for k, v in sorted(per_cat.items())},
            "errors": wrong,
        }
    return metrics


def markdown(meta, metrics):
    lines = [f"# Evaluation: {meta['case_file']}", "",
             f"- Date: {meta['date']}  |  commit `{meta['commit']}`  |  model `{meta['model']}` ({meta['mode']})",
             f"- Prompts: {meta['prompts']}",
             f"- Cases: {metrics['n_cases']} ({metrics['n_in_scope']} in scope, {metrics['n_out_of_scope']} out of scope)",
             f"- Step 1 scope correct: {metrics['scope_correct']}/{metrics['n_cases']}"]
    if meta.get("note"):
        lines.append(f"- Note: {meta['note']}")
    if meta.get("rescored_from"):
        lines.append(f"- Answers re-scored from `{meta['rescored_from']}` (no new model calls)")
    lines += ["", "| Arm | Accuracy | Wilson 95% | Confident wrong | Answered: right/total | Abstain recall | Abstain precision | Kit accuracy |",
              "|---|---|---|---|---|---|---|---|"]
    for arm, m in metrics["arms"].items():
        kit = f"{m['kit_accuracy'][0]}/{m['kit_accuracy'][1]}" if m["kit_accuracy"] else "n/a"
        lines.append(f"| {arm} | {m['accuracy'][0]}/{m['accuracy'][1]} | {m['accuracy_wilson95']} | "
                     f"{m['confident_wrong']} | {m['answered_right'][0]}/{m['answered_right'][1]} | "
                     f"{m['abstain_recall'][0]}/{m['abstain_recall'][1]} | "
                     f"{m['abstain_precision'][0]}/{m['abstain_precision'][1]} | {kit} |")
    for arm, m in metrics["arms"].items():
        lines += ["", f"## {arm}: errors"]
        lines += [f"- {e['id']} ({e['category']}): expected {e['expected']}, got {e['answer']}" for e in m["errors"]] or ["- none"]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case_file")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--audit-dir", default="audit/eval")
    ap.add_argument("--rescore", metavar="RESULTS_JSON", help="re-score saved answers; no model calls")
    ap.add_argument("--note", default="", help="free-text note stored with the results")
    args = ap.parse_args()
    cases = [json.loads(line) for line in open(args.case_file, encoding="utf8") if line.strip()]
    if args.rescore:
        old = json.load(open(args.rescore, encoding="utf8"))
        meta = dict(old["meta"], note=args.note, rescored_from=os.path.relpath(args.rescore, ROOT),
                    rescored_on=datetime.date.today().isoformat())
        _write(args, meta, score(cases, old["rows"]), old["rows"], suffix="_rescored")
        return
    config = get_config()
    if not config["api_key"]:
        sys.exit("No DEEPSEEK_API_KEY in the environment or .env; nothing was sent.")
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "seqseec", "prompts", "library"], cwd=ROOT,
                                capture_output=True, text=True).stdout.strip())
    meta = {"case_file": os.path.basename(args.case_file), "date": datetime.date.today().isoformat(),
            "commit": commit + ("-dirty" if dirty else ""), "model": config["model"], "mode": config["mode"],
            "prompts": {"extract": EXTRACT_PROMPT, "infer": INFER_PROMPT, "baseline": BASELINE_PROMPT_ID},
            "note": args.note}
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        rows = list(pool.map(lambda c: run_case(c, config, args.audit_dir), cases))
    _write(args, meta, score(cases, rows), rows)


def _write(args, meta, metrics, rows, suffix=""):
    stem = f"{os.path.splitext(meta['case_file'])[0]}_{meta['date']}_{meta['commit']}{suffix}"
    out = os.path.join(ROOT, "eval", "results", stem)
    n = 1
    while os.path.exists(out + ".json"):
        n += 1
        out = os.path.join(ROOT, "eval", "results", f"{stem}_run{n}")
    with open(out + ".json", "w", encoding="utf8") as f:
        json.dump({"meta": meta, "metrics": metrics, "rows": rows}, f, indent=2, ensure_ascii=False)
    with open(out + ".md", "w", encoding="utf8") as f:
        f.write(markdown(meta, metrics))
    print(markdown(meta, metrics))
    print(f"Wrote {out}.json and .md")


if __name__ == "__main__":
    main()
