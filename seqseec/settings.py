# File: seqseec/settings.py
# Version: 0.1.2
# Last modified: 2026-11-20 (Track B)
# Change: Removed references to the retired team plan document (comments only).
"""Step 6: translate a library orientation into downstream tool settings.

This is a fixed lookup table, not an LLM call. Given an
orientation (FR, RF or UNSTRANDED) and a layout (PE or SE), it returns the
setting that each downstream tool needs.

Orientation conventions (same as seqseec.datacheck):
  FR          read 1 on the transcript strand        (fr-secondstrand)
  RF          read 1 antisense to the transcript     (fr-firststrand; dUTP chemistry)
  UNSTRANDED  no strand information                  (fr-unstranded)

Every value was checked against the tool's official documentation or source
code on 2026-11-18. SOURCES records where each
check came from. Re-check whenever a tool version changes.
"""
from seqseec.datacheck import FORWARD_PATTERN, REVERSE_PATTERN

ORIENTATIONS = ("FR", "RF", "UNSTRANDED")
LAYOUTS = ("PE", "SE")

# Text used where the correct action is to leave the option out.
UNSET = "(leave unset: the default is unstranded)"

_ORIENTATION_ALIASES = {
    "FR": "FR", "FR-SECONDSTRAND": "FR",
    "RF": "RF", "FR-FIRSTSTRAND": "RF",
    "UNSTRANDED": "UNSTRANDED", "FR-UNSTRANDED": "UNSTRANDED",
}
_LAYOUT_ALIASES = {
    "PE": "PE", "PAIRED": "PE", "PAIRED-END": "PE",
    "SE": "SE", "SINGLE": "SE", "SINGLE-END": "SE",
}

LIBRARY_TYPE = {"FR": "fr-secondstrand", "RF": "fr-firststrand", "UNSTRANDED": "fr-unstranded"}

# tool -> layout -> orientation -> setting
TOOLS = {
    "featureCounts": {
        "PE": {"FR": "-s 1", "RF": "-s 2", "UNSTRANDED": "-s 0"},
        "SE": {"FR": "-s 1", "RF": "-s 2", "UNSTRANDED": "-s 0"},
    },
    "HISAT2": {
        "PE": {"FR": "--rna-strandness FR", "RF": "--rna-strandness RF", "UNSTRANDED": UNSET},
        "SE": {"FR": "--rna-strandness F", "RF": "--rna-strandness R", "UNSTRANDED": UNSET},
    },
    "Salmon": {
        "PE": {"FR": "-l ISF", "RF": "-l ISR", "UNSTRANDED": "-l IU"},
        "SE": {"FR": "-l SF", "RF": "-l SR", "UNSTRANDED": "-l U"},
    },
    "kallisto": {
        "PE": {"FR": "--fr-stranded", "RF": "--rf-stranded", "UNSTRANDED": UNSET},
        "SE": {"FR": "--fr-stranded", "RF": "--rf-stranded", "UNSTRANDED": UNSET},
    },
    "HTSeq": {
        "PE": {"FR": "-s yes", "RF": "-s reverse", "UNSTRANDED": "-s no"},
        "SE": {"FR": "-s yes", "RF": "-s reverse", "UNSTRANDED": "-s no"},
    },
    "STAR": {
        "PE": {"FR": "ReadsPerGene.out.tab column 3", "RF": "ReadsPerGene.out.tab column 4",
               "UNSTRANDED": "ReadsPerGene.out.tab column 2"},
        "SE": {"FR": "ReadsPerGene.out.tab column 3", "RF": "ReadsPerGene.out.tab column 4",
               "UNSTRANDED": "ReadsPerGene.out.tab column 2"},
    },
}

NOTES = {
    "featureCounts": "Option -s of featureCounts (Subread).",
    "HISAT2": "Option --rna-strandness at alignment time.",
    "Salmon": "Library type, option -l of salmon quant. 'A' (auto-detect) is an alternative.",
    "kallisto": "Option of kallisto quant; with --single it refers to the single read.",
    "HTSeq": "Option -s of htseq-count. Its default is 'yes', so unstranded data needs '-s no' set explicitly.",
    "STAR": "Which column of ReadsPerGene.out.tab (--quantMode GeneCounts) to use.",
}


# Where each row was verified (2026-11-18) and what that source states.
SOURCES = {
    "featureCounts": ("https://github.com/ShiLab-Bioinformatics/subread/blob/master/src/readSummary.c",
                      "usage text: -s 0 (unstranded), 1 (stranded), 2 (reversely stranded); default 0"),
    "HISAT2": ("https://daehwankimlab.github.io/hisat2/manual/",
               "--rna-strandness: F/R single-end, FR/RF paired-end; default unstranded; "
               "fr-firststrand = R/RF, fr-secondstrand = F/FR"),
    "Salmon": ("https://salmon.readthedocs.io/en/latest/library_type.html",
               "ISF/ISR/IU paired-end, SF/SR/U single-end; fr-firststrand = ISR/SR, fr-secondstrand = ISF/SF"),
    "kallisto": ("https://pachterlab.github.io/kallisto/manual",
                 "--fr-stranded: first read forward; --rf-stranded: first read reverse. The manual does not "
                 "mention single-end; src/main.cpp of v0.44.0 does not restrict these flags to paired-end"),
    "HTSeq": ("https://htseq.readthedocs.io/en/latest/htseqcount.html",
              "-s yes/no/reverse; default yes; yes = read 1 (or single read) on the feature's strand"),
    "STAR": ("https://github.com/alexdobin/STAR/blob/master/extras/doc-latex/STARmanual.tex",
             "ReadsPerGene.out.tab: column 2 unstranded, column 3 = htseq-count -s yes, column 4 = -s reverse"),
}


def normalize_orientation(value):
    """Map FR / RF / UNSTRANDED or their fr-* library-type names to FR, RF or UNSTRANDED."""
    key = str(value).strip().upper().replace("_", "-")
    if key not in _ORIENTATION_ALIASES:
        raise ValueError(f"Unknown orientation: {value!r}")
    return _ORIENTATION_ALIASES[key]


def normalize_layout(value):
    """Map PE / SE (or paired / single) to PE or SE."""
    key = str(value).strip().upper().replace("_", "-")
    if key not in _LAYOUT_ALIASES:
        raise ValueError(f"Unknown layout: {value!r}")
    return _LAYOUT_ALIASES[key]


def get_settings(orientation, layout="PE"):
    """Return the downstream settings for one orientation and layout.

    Result:
      {"orientation", "layout", "library_type", "rseqc_dominant",
       "tools": {tool: {"setting": str, "note": str}}}
    rseqc_dominant is the RSeQC pattern expected to dominate, or None if unstranded.
    """
    o, lay = normalize_orientation(orientation), normalize_layout(layout)
    rseqc = {"FR": FORWARD_PATTERN[lay], "RF": REVERSE_PATTERN[lay], "UNSTRANDED": None}[o]
    return {
        "orientation": o,
        "layout": lay,
        "library_type": LIBRARY_TYPE[o],
        "rseqc_dominant": rseqc,
        "tools": {tool: {"setting": table[lay][o], "note": NOTES[tool]} for tool, table in TOOLS.items()},
    }
