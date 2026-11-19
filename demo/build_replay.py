# File: demo/build_replay.py
# Version: 0.1.0
# Last modified: 2026-11-19 (Track B)
# Change: Build the static replay page (demo/index.html) from saved reports and the latest evaluation result.
"""Build demo/index.html, a static replay of pre-computed SeqSeec runs.

Inputs (all already in the repo):
  demo/notes/*.txt          the synthetic notes used for each demo case
  demo/reports/*.json       `seqseec run --format json` reports, one per case (name order = page order)
  eval/results/*.json       evaluation results; the newest held-out file is shown

The page is plain HTML + inline JS with the data embedded, so it works offline and
on any static host. It says clearly that it replays saved runs; nothing runs live.

Usage (repo root):  python demo/build_replay.py
"""
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "demo")

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


def load_eval():
    files = sorted(glob.glob(os.path.join(ROOT, "eval", "results", "cases_heldout_*.json")), key=os.path.getmtime)
    if not files:
        return None
    data = json.load(open(files[-1], encoding="utf8"))
    cases = {}
    with open(os.path.join(ROOT, "eval", "cases_heldout.jsonl"), encoding="utf8") as f:
        for line in f:
            c = json.loads(line)
            cases[c["id"]] = {"category": c["category"], "source": c["source"], "expected": c["expected_document"]}
    rows = [{"id": r["id"], **cases[r["id"]], "rules": r["rules"]["answer"], "rag": r["rag"]["answer"],
             "norag": r["norag"]["answer"]} for r in data["rows"]]
    return {"meta": data["meta"], "metrics": data["metrics"], "rows": sorted(rows, key=lambda r: r["id"]),
            "file": os.path.relpath(files[-1], ROOT)}


TEMPLATE = open(os.path.join(DEMO, "replay_template.html"), encoding="utf8").read()


def main():
    payload = {"cases": load_cases(), "eval": load_eval()}
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    out = TEMPLATE.replace("/*__DATA__*/null", data)
    with open(os.path.join(DEMO, "index.html"), "w", encoding="utf8") as f:
        f.write(out)
    print(f"Wrote demo/index.html ({len(payload['cases'])} cases, eval: "
          f"{payload['eval']['file'] if payload['eval'] else 'none'})")


if __name__ == "__main__":
    main()
