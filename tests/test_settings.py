# File: tests/test_settings.py
# Version: 0.1.0
# Last modified: 2026-11-18 (XD)
# Change: Unit tests for the step 6 settings lookup table.
import pytest

from seqseec.datacheck import FORWARD_PATTERN, REVERSE_PATTERN
from seqseec.settings import SOURCES, TOOLS, UNSET, get_settings, normalize_layout, normalize_orientation

# Plan §5 settings table (paired-end).
PE_TABLE = {
    "FR": {"featureCounts": "-s 1", "HISAT2": "--rna-strandness FR", "Salmon": "-l ISF",
           "kallisto": "--fr-stranded", "HTSeq": "-s yes", "STAR": "ReadsPerGene.out.tab column 3"},
    "RF": {"featureCounts": "-s 2", "HISAT2": "--rna-strandness RF", "Salmon": "-l ISR",
           "kallisto": "--rf-stranded", "HTSeq": "-s reverse", "STAR": "ReadsPerGene.out.tab column 4"},
    "UNSTRANDED": {"featureCounts": "-s 0", "HISAT2": UNSET, "Salmon": "-l IU",
                   "kallisto": UNSET, "HTSeq": "-s no", "STAR": "ReadsPerGene.out.tab column 2"},
}


@pytest.mark.parametrize("orientation", ["FR", "RF", "UNSTRANDED"])
def test_paired_end_table(orientation):
    tools = get_settings(orientation, "PE")["tools"]
    assert {t: v["setting"] for t, v in tools.items()} == PE_TABLE[orientation]


@pytest.mark.parametrize("orientation,hisat2,salmon", [
    ("FR", "--rna-strandness F", "-l SF"),
    ("RF", "--rna-strandness R", "-l SR"),
    ("UNSTRANDED", UNSET, "-l U"),
])
def test_single_end_differences(orientation, hisat2, salmon):
    tools = get_settings(orientation, "SE")["tools"]
    assert tools["HISAT2"]["setting"] == hisat2
    assert tools["Salmon"]["setting"] == salmon
    # Tools whose option does not depend on layout.
    for tool in ("featureCounts", "kallisto", "HTSeq", "STAR"):
        assert tools[tool]["setting"] == PE_TABLE[orientation][tool]


def test_rseqc_pattern_matches_datacheck():
    for layout in ("PE", "SE"):
        assert get_settings("FR", layout)["rseqc_dominant"] == FORWARD_PATTERN[layout]
        assert get_settings("RF", layout)["rseqc_dominant"] == REVERSE_PATTERN[layout]
        assert get_settings("UNSTRANDED", layout)["rseqc_dominant"] is None


def test_library_type_names():
    assert get_settings("FR")["library_type"] == "fr-secondstrand"
    assert get_settings("RF")["library_type"] == "fr-firststrand"
    assert get_settings("UNSTRANDED")["library_type"] == "fr-unstranded"


def test_every_tool_has_a_note():
    for tool in get_settings("RF")["tools"].values():
        assert tool["note"]


def test_every_tool_has_a_verification_source():
    assert set(SOURCES) == set(TOOLS)
    for url, statement in SOURCES.values():
        assert url.startswith("https://") and statement


@pytest.mark.parametrize("value,expected", [
    ("rf", "RF"), (" FR ", "FR"), ("fr-firststrand", "RF"), ("fr_secondstrand", "FR"),
    ("fr-unstranded", "UNSTRANDED"), ("unstranded", "UNSTRANDED"),
])
def test_orientation_aliases(value, expected):
    assert normalize_orientation(value) == expected


@pytest.mark.parametrize("value,expected", [("pe", "PE"), ("paired-end", "PE"), ("single", "SE")])
def test_layout_aliases(value, expected):
    assert normalize_layout(value) == expected


@pytest.mark.parametrize("bad", ["INCONCLUSIVE", "ISR", "", None])
def test_unknown_orientation_rejected(bad):
    with pytest.raises(ValueError):
        get_settings(bad)


def test_unknown_layout_rejected():
    with pytest.raises(ValueError):
        get_settings("RF", "long-read")
