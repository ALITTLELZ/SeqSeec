# File: tests/toy/run_smoke.py
# Version: 0.1.0
# Last modified: 2026-11-08 (Track B)
# Change: End-to-end smoke test of check_strandedness on simulated reads.
"""Run the local strandedness tool on simulated data with known orientation.

Needs the seqseec-tools conda env (envs/tools-osx64.yml). Generates the toy data
if missing, runs 7 cases, checks each call, and writes smoke_results.json.

Usage (from the repo root):
  python tests/toy/run_smoke.py [--env seqseec-tools]
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from seqseec.datacheck import run_check_strandedness  # noqa: E402

OUT = os.path.join(ROOT, "tests", "toy", "out")

# (case name, reads_1, reads_2, expected call)
CASES = [
    ("PE_FR", "FR_R1.fq.gz", "FR_R2.fq.gz", "FR"),
    ("PE_RF", "RF_R1.fq.gz", "RF_R2.fq.gz", "RF"),
    ("PE_UN", "UN_R1.fq.gz", "UN_R2.fq.gz", "UNSTRANDED"),
    ("PE_RF_swapped", "RF_R2.fq.gz", "RF_R1.fq.gz", "FR"),  # R1/R2 swap flips orientation
    ("SE_FR", "FR_R1.fq.gz", None, "FR"),
    ("SE_RF", "RF_R1.fq.gz", None, "RF"),
    ("SE_UN", "UN_R1.fq.gz", None, "UNSTRANDED"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="seqseec-tools")
    args = ap.parse_args()
    if not os.path.exists(os.path.join(OUT, "transcripts.fa")):
        subprocess.run([sys.executable, os.path.join(ROOT, "tests", "toy", "make_toy_data.py"), "--out", OUT],
                       check=True)
    results, failures = [], 0
    for name, r1, r2, expected in CASES:
        res = run_check_strandedness(
            gtf=os.path.join(OUT, "annotation.gtf"), transcripts=os.path.join(OUT, "transcripts.fa"),
            reads_1=os.path.join(OUT, r1), reads_2=os.path.join(OUT, r2) if r2 else None,
            index_name=f"toy_{args.env}", env=args.env)
        ok = res["call"] == expected
        failures += not ok
        results.append({"case": name, "expected": expected, "ok": ok, **res})
        print(f"{'PASS' if ok else 'FAIL'}  {name:14s} expected {expected:10s} got {res['call']:10s} "
              f"fwd={res['forward_fraction']:.4f} rev={res['reverse_fraction']:.4f} failed={res['failed_fraction']:.4f}")
    with open(os.path.join(OUT, "smoke_results.json"), "w") as f:
        json.dump({"date": date.today().isoformat(), "env": args.env, "results": results}, f, indent=2)
    print(f"\n{len(CASES) - failures}/{len(CASES)} passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
