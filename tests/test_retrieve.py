# File: tests/test_retrieve.py
# Version: 0.1.0
# Last modified: 2026-11-19 (Track B)
# Change: Tests for the kit registry files and step 2 retrieval (aliases, look-alikes, keyword fallback).
import csv

import pytest

from seqseec.retrieve import ALIASES_PATH, REGISTRY_PATH, load_aliases, load_registry, retrieve

REG = load_registry()


def ids(notes, fields=None):
    return [c["kit_id"] for c in retrieve(notes, fields)["candidates"]]


def test_every_registry_row_has_source_and_quote():
    assert len(REG) >= 9
    for kid, row in REG.items():
        assert row["source_url"].startswith("https://") and len(row["source_quote"]) > 20, kid
        assert row["accessed"] and row["checked_by"], kid


def test_every_kit_has_an_alias_and_aliases_point_to_real_kits():
    aliases = load_aliases(REG)
    covered = {k for _, _, kit_ids in aliases for k in kit_ids}
    assert covered == set(REG)
    with open(ALIASES_PATH, newline="", encoding="utf8") as f:
        assert len(list(csv.DictReader(f))) == len(aliases)


def test_bad_registry_row_is_refused(tmp_path):
    bad = tmp_path / "reg.csv"
    with open(REGISTRY_PATH, encoding="utf8") as f:
        header, first = f.readline(), f.readline()
    bad.write_text(header + first.replace(",RF,", ",SIDEWAYS,", 1), encoding="utf8")
    with pytest.raises(ValueError):
        load_registry(bad)


@pytest.mark.parametrize("notes,expected", [
    ("built with the NEBNext Ultra II Directional RNA Library Prep Kit (E7760)", ["nebnext_ultra2_directional"]),
    ("NEBNext Ultra II RNA Library Prep Kit for Illumina (E7770)", ["nebnext_ultra2_nondirectional"]),
    ("TruSeq Stranded mRNA LT kit", ["truseq_stranded_mrna"]),
    ("Illumina TruSeq RNA Sample Prep Kit v2", ["truseq_rna_v2"]),
    ("CORALL Total RNA-Seq kit (Lexogen)", ["lexogen_corall"]),
    ("KAPA mRNA HyperPrep Kit (Roche)", ["kapa_mrna_hyperprep"]),
])
def test_named_kits(notes, expected):
    r = retrieve(notes)
    assert r["method"] == "alias" and ids(notes) == expected


def test_family_name_gives_both_look_alikes():
    found = retrieve("Libraries: NEBNext Ultra II kit, PE150.")["candidates"]
    assert {c["kit_id"] for c in found} == {"nebnext_ultra2_directional", "nebnext_ultra2_nondirectional"}
    assert {c["orientation"] for c in found} == {"RF", "UNSTRANDED"}


def test_longer_name_hides_family_name():
    assert ids("NEBNext Ultra II Directional RNA Library Prep Kit") == ["nebnext_ultra2_directional"]


def test_chemistry_only_when_no_kit_named():
    assert ids("a dUTP second-strand protocol was used") == ["chem_dutp"]
    assert ids("TruSeq Stranded mRNA (dUTP method)") == ["truseq_stranded_mrna"]


def test_keyword_fallback_for_reordered_name():
    r = retrieve("KAPA HyperPrep stranded mRNA kit (Roche)")
    assert r["method"] == "keyword" and r["candidates"][0]["kit_id"] == "kapa_mrna_hyperprep"


def test_nothing_named():
    assert retrieve("Total RNA was sequenced on a NovaSeq 6000.") == {"chunks": [], "candidates": [], "method": "none"}


def test_extracted_kit_name_is_searched_too():
    assert ids("see attached", {"kit_name": "TruSeq Stranded Total RNA"}) == ["truseq_stranded_total"]


def test_chunks_carry_vendor_quote_verbatim():
    chunk = retrieve("TruSeq RNA v2")["chunks"][0]
    assert REG["truseq_rna_v2"]["source_quote"] in chunk["text"]
    assert set(chunk) <= {"chunk_id", "text", "kit", "version", "vendor", "source", "page", "date", "score"}
