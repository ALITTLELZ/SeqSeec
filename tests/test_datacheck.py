# File: tests/test_datacheck.py
# Version: 0.1.0
# Last modified: 2026-11-08 (Track B)
# Change: Unit tests for RSeQC output parsing and the data-call thresholds.
import pytest

from seqseec.datacheck import call_orientation, parse_infer_experiment

PE_RF = """This is PairEnd Data
Fraction of reads failed to determine: 0.0000
Fraction of reads explained by "1++,1--,2+-,2-+": 0.0000 (0.0% of explainable reads)
Fraction of reads explained by "1+-,1-+,2++,2--": 1.0000 (100.0% of explainable reads)
"""

SE_FR = """This is SingleEnd Data
Fraction of reads failed to determine: 0.0000
Fraction of reads explained by "++,--": 1.0000 (100.0% of explainable reads)
Fraction of reads explained by "+-,-+": 0.0000 (0.0% of explainable reads)
"""


def test_parse_paired_end():
    p = parse_infer_experiment(PE_RF)
    assert p == {"layout": "PE", "failed": 0.0, "forward": 0.0, "reverse": 1.0}


def test_parse_single_end():
    p = parse_infer_experiment(SE_FR)
    assert p["layout"] == "SE" and p["forward"] == 1.0


def test_parse_ignores_noise_lines():
    noisy = "Intel MKL WARNING: something\n\n" + PE_RF
    assert parse_infer_experiment(noisy)["reverse"] == 1.0


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        parse_infer_experiment("kallisto crashed")


def _call(fwd, rev, failed=0.0, layout="PE"):
    return call_orientation({"layout": layout, "failed": failed, "forward": fwd, "reverse": rev})["call"]


@pytest.mark.parametrize("fwd,rev,failed,expected", [
    (0.95, 0.04, 0.01, "FR"),
    (0.03, 0.96, 0.01, "RF"),
    (0.50, 0.49, 0.01, "UNSTRANDED"),
    (0.75, 0.24, 0.01, "INCONCLUSIVE"),
    (0.45, 0.04, 0.51, "INVALID"),        # most reads unassignable
    (0.90, 0.10, 0.00, "INCONCLUSIVE"),   # exactly 0.9 is not "> 0.9"
    (0.60, 0.40, 0.00, "INCONCLUSIVE"),   # exactly 0.6 is not "< 0.6"
])
def test_thresholds(fwd, rev, failed, expected):
    assert _call(fwd, rev, failed) == expected


def test_share_uses_explainable_reads_only():
    # 40% failed, but of the assignable 60%, 95% are reverse -> still RF.
    assert _call(0.03, 0.57, failed=0.40) == "RF"


def test_summary_has_no_paths_or_sequences():
    out = call_orientation(parse_infer_experiment(PE_RF))
    allowed = {"layout", "failed_fraction", "forward_fraction", "reverse_fraction",
               "forward_share", "reverse_share", "call", "reason"}
    assert set(out) <= allowed
