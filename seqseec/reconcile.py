# File: seqseec/reconcile.py
# Version: 0.2.1
# Last modified: 2026-11-20 (Track B)
# Change: Removed references to the retired team plan document (comments only).
"""Step 5: reconcile what the documents say with what the reads show.

Deterministic decision table. Documents show what was *intended*;
reads show what the files *are*. Neither silently overrides the other.

| Document     | Data                  | State        | Settings                                   |
|--------------|-----------------------|--------------|--------------------------------------------|
| OUT_OF_SCOPE | anything              | OUT_OF_SCOPE | none                                       |
| X            | X                     | CONCORDANT   | from X                                     |
| X            | other direction       | CONFLICT     | provisional, from data; review required    |
| X            | INCONCLUSIVE          | INCONCLUSIVE | none                                       |
| X            | INVALID or not run    | UNVERIFIED   | provisional, from documents; review needed |
| INSUFFICIENT | FR / RF / UNSTRANDED  | DATA_ONLY    | from data; kit not identified              |
| INSUFFICIENT | no direction          | INSUFFICIENT | none ("Not sufficient information")        |

X is FR, RF or UNSTRANDED. AMBIGUOUS from step 3 (candidate kits disagree
and the notes cannot separate them) is treated as INSUFFICIENT and flagged.
OUT_OF_SCOPE covers protocols outside SeqSeec's scope (e.g. Nanopore, PacBio, single-cell).

Result fields that say how far to trust the settings:
  settings_basis               "documents and data" | "data" | "documents" | None
  documents_confirmed_by_data  True only for CONCORDANT: the reads agree with the documents
  provisional                  settings may change after a person reviews them
  human_review_required        a person must look before the settings are used

The result holds labels and settings only, with no paths or read data, so it
can go into the step 7 LLM payload.
"""
import re

from seqseec.settings import ORIENTATIONS, get_settings, normalize_layout, normalize_orientation

STATES = ("CONCORDANT", "CONFLICT", "INCONCLUSIVE", "UNVERIFIED", "DATA_ONLY", "INSUFFICIENT", "OUT_OF_SCOPE")

_DOC_NO_ANSWER = {"INSUFFICIENT", "NOT SUFFICIENT INFORMATION", "AMBIGUOUS"}
_DOC_OUT_OF_SCOPE = {"OUT OF SCOPE"}
_DATA_NO_DIRECTION = {"INCONCLUSIVE": "INCONCLUSIVE", "INVALID": "INVALID", "NOT RUN": "NOT_RUN"}

INSUFFICIENT_MESSAGE = "Not sufficient information"
OUT_OF_SCOPE_MESSAGE = ("The notes describe a protocol outside SeqSeec's scope (Illumina short-read bulk RNA-seq), "
                        "such as Nanopore, PacBio or single-cell. No settings are given.")

INCONCLUSIVE_CHECKS = [
    "Check for genomic DNA contamination, which adds reads in both directions.",
    "Run read quality checks (for example FastQC).",
    "Confirm that the reference and annotation match the species.",
]
INVALID_CHECKS = ["Most reads could not be assigned; check that the reference, annotation and species match."]


def _canon(value):
    """Upper-case and treat spaces, underscores and hyphens alike: 'not_sufficient-information' -> 'NOT SUFFICIENT INFORMATION'."""
    return re.sub(r"[\s_-]+", " ", str(value).strip().upper())


def _document(value):
    """Return (orientation | "INSUFFICIENT" | "OUT_OF_SCOPE", ambiguous flag)."""
    if value is None:
        return "INSUFFICIENT", False
    key = _canon(value)
    if key in _DOC_OUT_OF_SCOPE:
        return "OUT_OF_SCOPE", False
    if key in _DOC_NO_ANSWER:
        return "INSUFFICIENT", key == "AMBIGUOUS"
    return normalize_orientation(value), False


def _data(value):
    """Accept a call string, a datacheck result dict, or None. Return (call, layout or None)."""
    layout = None
    if isinstance(value, dict):
        layout, value = value.get("layout"), value.get("call")
    if value is None:
        return "NOT_RUN", layout
    key = _canon(value)
    if key in _DATA_NO_DIRECTION:
        return _DATA_NO_DIRECTION[key], layout
    return normalize_orientation(value), layout


def _no_direction_checks(call):
    return {"INCONCLUSIVE": INCONCLUSIVE_CHECKS, "INVALID": INVALID_CHECKS}.get(call, [])


def _conflict_causes(doc, data):
    if "UNSTRANDED" not in (doc, data):  # FR vs RF
        return [
            "R1 and R2 files swapped (this flips FR and RF).",
            "Kit or kit version differs from the one in the notes; some kits changed read orientation between versions.",
            "Sample or file mix-up.",
        ]
    if data == "UNSTRANDED":  # notes say stranded
        return [
            "The notes may be wrong: the library may have been made with a non-stranded kit.",
            "The strand-marking step of the library prep may have failed.",
            "Sample or file mix-up.",
        ]
    return [  # notes say unstranded, data is stranded
        "The notes may be wrong or incomplete: a stranded kit may have been used.",
        "Sample or file mix-up.",
    ]


def reconcile(document, data, layout=None):
    """Combine the step 3 document result with the step 4 data result.

    document: "FR" | "RF" | "UNSTRANDED" | "INSUFFICIENT" | "AMBIGUOUS" | "OUT_OF_SCOPE" | None
              (fr-* library-type names are accepted; spaces, underscores and hyphens are interchangeable)
    data:     "FR" | "RF" | "UNSTRANDED" | "INCONCLUSIVE" | "INVALID" | None (not run),
              or the dict returned by seqseec.datacheck
    layout:   "PE" or "SE"; a layout in the data dict takes precedence; default "PE"
    """
    doc, ambiguous = _document(document)
    call, data_layout = _data(data)
    layout = normalize_layout(data_layout or layout or "PE")

    doc_known, data_known = doc in ORIENTATIONS, call in ORIENTATIONS
    orientation, basis = None, None
    provisional = review = False
    causes, checks = [], []

    if doc == "OUT_OF_SCOPE":
        state = "OUT_OF_SCOPE"
        message = OUT_OF_SCOPE_MESSAGE
    elif doc_known and data_known and doc == call:
        state, orientation, basis = "CONCORDANT", doc, "documents and data"
        message = f"Documents and data agree: {doc}."
    elif doc_known and data_known:
        state, orientation, basis = "CONFLICT", call, "data"
        provisional = review = True
        causes = _conflict_causes(doc, call)
        message = (f"Documents indicate {doc} but the reads look {call}. The settings follow the data and are "
                   f"provisional until a person reviews the likely causes.")
        if call == "UNSTRANDED":
            message += " The notes may be wrong."
    elif doc_known and call == "INCONCLUSIVE":
        state = "INCONCLUSIVE"
        review = True
        checks = INCONCLUSIVE_CHECKS
        message = (f"Documents indicate {doc}, but the data check is inconclusive (dominant direction between "
                   f"60% and 90%). No settings are given automatically.")
    elif doc_known:  # data INVALID or NOT_RUN
        state, orientation, basis = "UNVERIFIED", doc, "documents"
        provisional = review = True
        checks = _no_direction_checks(call)
        message = f"Documents indicate {doc}. This has not been verified against the data."
    elif data_known:
        state, orientation, basis = "DATA_ONLY", call, "data"
        if ambiguous:
            message = (f"The notes match several kits that differ in orientation. The reads look {call}, "
                       f"which can be used to choose among those candidate kits.")
        else:
            message = f"The reads look {call}. The kit could not be identified from the notes."
    else:
        state = "INSUFFICIENT"
        checks = _no_direction_checks(call)
        message = INSUFFICIENT_MESSAGE

    return {
        "state": state,
        "document_orientation": doc,
        "document_ambiguous": ambiguous,
        "data_call": call,
        "layout": layout,
        "orientation": orientation,
        "settings_basis": basis,
        "documents_confirmed_by_data": state == "CONCORDANT",
        "provisional": provisional,
        "human_review_required": review,
        "message": message,
        "likely_causes": causes,
        "suggested_checks": list(checks),
        "settings": get_settings(orientation, layout) if orientation else None,
    }
