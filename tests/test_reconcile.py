# File: tests/test_reconcile.py
# Version: 0.1.0
# Last modified: 2026-11-18 (XD)
# Change: Unit tests covering every cell of the step 5 decision table.
import pytest

from seqseec.reconcile import INSUFFICIENT_MESSAGE, STATES, reconcile

# Plan §5 decision table, written out cell by cell.
# Rows: document result. Columns: data call (None = data check not run).
DATA_COLUMNS = ["FR", "RF", "UNSTRANDED", "INCONCLUSIVE", "INVALID", None]
GRID = {
    "FR":           ["CONCORDANT", "CONFLICT", "CONFLICT", "INCONCLUSIVE", "UNVERIFIED", "UNVERIFIED"],
    "RF":           ["CONFLICT", "CONCORDANT", "CONFLICT", "INCONCLUSIVE", "UNVERIFIED", "UNVERIFIED"],
    "UNSTRANDED":   ["CONFLICT", "CONFLICT", "CONCORDANT", "INCONCLUSIVE", "UNVERIFIED", "UNVERIFIED"],
    "INSUFFICIENT": ["DATA_ONLY", "DATA_ONLY", "DATA_ONLY", "INSUFFICIENT", "INSUFFICIENT", "INSUFFICIENT"],
}
CELLS = [(doc, data, GRID[doc][i]) for doc in GRID for i, data in enumerate(DATA_COLUMNS)]


@pytest.mark.parametrize("doc,data,expected", CELLS)
def test_decision_table(doc, data, expected):
    out = reconcile(doc, data)
    assert out["state"] == expected
    assert out["state"] in STATES


@pytest.mark.parametrize("doc,data,expected", CELLS)
def test_settings_present_only_with_an_orientation(doc, data, expected):
    out = reconcile(doc, data)
    if expected in ("INCONCLUSIVE", "INSUFFICIENT"):
        assert out["orientation"] is None and out["settings"] is None
    else:
        assert out["settings"]["orientation"] == out["orientation"]


def test_concordant_is_final():
    out = reconcile("RF", "RF")
    assert not out["provisional"] and not out["human_review_required"] and out["verified_by_data"]
    assert out["settings"]["tools"]["featureCounts"]["setting"] == "-s 2"


def test_conflict_follows_data_and_requires_review():
    out = reconcile("RF", "FR")
    assert out["orientation"] == "FR" and out["settings_basis"] == "data"
    assert out["provisional"] and out["human_review_required"]
    assert out["settings"]["tools"]["featureCounts"]["setting"] == "-s 1"
    assert any("swapped" in c for c in out["likely_causes"])


def test_stranded_notes_unstranded_data_flags_notes():
    out = reconcile("RF", "UNSTRANDED")
    assert out["state"] == "CONFLICT"
    assert "notes may be wrong" in out["message"].lower()
    assert any("non-stranded kit" in c for c in out["likely_causes"])


def test_unstranded_notes_stranded_data():
    out = reconcile("UNSTRANDED", "RF")
    assert out["orientation"] == "RF"
    assert any("stranded kit may have been used" in c for c in out["likely_causes"])


def test_inconclusive_suggests_checks():
    out = reconcile("FR", "INCONCLUSIVE")
    assert out["human_review_required"]
    assert any("contamination" in c for c in out["suggested_checks"])


def test_unverified_uses_documents():
    out = reconcile("RF", None)
    assert out["orientation"] == "RF" and out["settings_basis"] == "documents"
    assert out["provisional"] and not out["verified_by_data"]


def test_data_only_states_kit_unknown():
    out = reconcile("INSUFFICIENT", "RF")
    assert out["orientation"] == "RF" and not out["provisional"]
    assert "kit could not be identified" in out["message"]


def test_insufficient_message():
    assert reconcile(None, "INVALID")["message"] == INSUFFICIENT_MESSAGE


def test_ambiguous_document_is_flagged():
    out = reconcile("AMBIGUOUS", "RF")
    assert out["state"] == "DATA_ONLY" and out["document_ambiguous"]


def test_accepts_datacheck_dict_and_uses_its_layout():
    data = {"layout": "SE", "call": "RF", "forward_fraction": 0.02, "reverse_fraction": 0.97}
    out = reconcile("fr-firststrand", data, layout="PE")
    assert out["state"] == "CONCORDANT" and out["layout"] == "SE"
    assert out["settings"]["tools"]["Salmon"]["setting"] == "-l SR"


def test_layout_argument_used_without_data():
    assert reconcile("RF", None, layout="SE")["settings"]["tools"]["Salmon"]["setting"] == "-l SR"
    assert reconcile("RF", None)["layout"] == "PE"


@pytest.mark.parametrize("doc,data", [("XYZ", "RF"), ("RF", "sideways")])
def test_unknown_values_rejected(doc, data):
    with pytest.raises(ValueError):
        reconcile(doc, data)
