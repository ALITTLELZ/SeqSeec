# File: demo/build_replay.py
# Version: 0.2.0
# Last modified: 2026-11-20 (XD)
# Change: Name the eval run to show (EVAL_RESULT, or --eval) instead of guessing from file times; write LF; --out.
"""Build demo/index.html, a static replay of pre-computed SeqSeec runs.

Inputs (all already in the repo):
  demo/notes/*.txt          the synthetic notes used for each demo case
  demo/reports/*.json       `seqseec run --format json` reports, one per case (name order = page order)
  eval/results/<EVAL_RESULT> the evaluation run to show (or --eval FILE)

The page is plain HTML + inline JS with the data embedded, so it works offline and
on any static host. It says clearly that it replays saved runs; nothing runs live.

The eval run is named, not guessed: file times are the same in a fresh clone,
and run 1's commit survives only in a tag, so neither can order the runs. After a
new eval run, update EVAL_RESULT (or pass --eval) and rebuild.

Usage (repo root):  python demo/build_replay.py [--eval eval/results/<file>.json] [--out demo/index.html]
"""
import argparse
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "demo")
# Run 2 (labels second-checked). Run 1 is cases_heldout_2026-11-19_fba4c90.json.
EVAL_RESULT = "eval/results/cases_heldout_2026-11-19_e1c8bd6.json"

CASE_INFO = {
    "1_concordant": ("Documents and reads agree", "neb_directional",
                     "Notes name a dUTP kit; the reads (simulated, RF) agree."),
    "2_conflict_swapped": ("R1 and R2 swapped", "neb_directional",
                           "Same notes, but the read files were given in the wrong order."),
    "3_ambiguous_kit": ("Look-alike kit names", "neb_family",
                        "\"NEBNext Ultra II\" fits a stranded and an unstranded kit; the reads decide."),
    "4_unverified_no_reads": ("No reads yet", "corall",
                              "Only notes are available, so the answer is provisional."),
    "5_out_of_scope": ("Out of scope", "nanopore",
                       "Nanopore data is outside what SeqSeec handles; it says so."),
}


def load_cases():
    cases = []
    for path in sorted(glob.glob(os.path.join(DEMO, "reports", "*.json"))):
        key = os.path.splitext(os.path.basename(path))[0]
        title, notes_file, blurb = CASE_INFO.get(key, (key, None, ""))
        report = json.load(open(path, encoding="utf8"))
        notes = ""
        if notes_file:
            notes = open(os.path.join(DEMO, "notes", f"{notes_file}.txt"), encoding="utf8").read().strip()
        cases.append({"key": key, "title": title, "blurb": blurb, "notes": notes, "report": report})
    return cases


def load_eval(result=EVAL_RESULT):
    """Load one eval result file (path relative to the repo root, or absolute)."""
    path = result if os.path.isabs(result) else os.path.join(ROOT, result)
    if not os.path.exists(path):
        raise SystemExit(f"eval result not found: {result}")
    data = json.load(open(path, encoding="utf8"))
    cases = {}
    with open(os.path.join(ROOT, "eval", "cases_heldout.jsonl"), encoding="utf8") as f:
        for line in f:
            c = json.loads(line)
            cases[c["id"]] = {"category": c["category"], "source": c["source"], "expected": c["expected_document"]}
    rows = [{"id": r["id"], **cases[r["id"]], "rules": r["rules"]["answer"], "rag": r["rag"]["answer"],
             "norag": r["norag"]["answer"]} for r in data["rows"]]
    return {"meta": data["meta"], "metrics": data["metrics"], "rows": sorted(rows, key=lambda r: r["id"]),
            "file": os.path.relpath(path, ROOT).replace(os.sep, "/")}


TEMPLATE = open(os.path.join(DEMO, "replay_template.html"), encoding="utf8").read()


def build(result=EVAL_RESULT):
    """Return (page text, embedded data)."""
    payload = {"cases": load_cases(), "eval": load_eval(result)}
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<" + "\\" + "/")
    return TEMPLATE.replace("/*__DATA__*/null", data), payload


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the static replay page.")
    parser.add_argument("--eval", default=EVAL_RESULT, help=f"eval result file to show (default {EVAL_RESULT})")
    parser.add_argument("--out", default=os.path.join(DEMO, "index.html"), help="output file")
    args = parser.parse_args(argv)
    page, payload = build(args.eval)
    with open(args.out, "w", encoding="utf8", newline="\n") as f:  # LF on every OS
        f.write(page)
    print(f"Wrote {args.out} ({len(payload['cases'])} cases, eval: {payload['eval']['file']})")


if __name__ == "__main__":
    main()
