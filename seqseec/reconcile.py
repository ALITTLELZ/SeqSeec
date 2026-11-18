# File: seqseec/reconcile.py
# Version: 0.1.0
# Last modified: 2026-11-18 (XD)
# Change: Step 5 decision table reconciling document-inferred and data-observed orientation.
"""Step 5: reconcile what the documents say with what the reads show.

Deterministic decision table from plan §5. Documents show what was *intended*;
reads show what the files *are*. Neither silently overrides the other.

| Document     | Data                  | State        | Settings                                   |
|--------------|-----------------------|--------------|--------------------------------------------|
| X            | X                     | CONCORDANT   | from X                                     |
| X            | other direction       | CONFLICT     | provisional, from data; review required    |
| X            | INCONCLUSIVE          | INCONCLUSIVE | none                                       |
| X            | INVALID or not run    | UNVERIFIED   | provisional, from documents; review needed |
| INSUFFICIENT | FR / RF / UNSTRANDED  | DATA_ONLY    | from data; kit not identified              |
| INSUFFICIENT | no direction          | INSUFFICIENT | none ("Not sufficient information")        |

X is FR, RF or UNSTRANDED. AMBIGUOUS from step 3 (candidate kits disagree
and the notes cannot separate them) is treated as INSUFFICIENT and flagged.

The result holds labels and settings only, with no paths or read data, so it
can go into the step 7 LLM payload.
"""
from seqseec.settings import ORIENTATIONS, get_settings, normalize_layout, normalize_orientation

STATES = ("CONCORDANT", "CONFLICT", "INCONCLUSIVE", "UNVERIFIED", "DATA_ONLY", "INSUFFICIENT")

_DOC_NO_ANSWER = {"INSUFFICIENT", "NOT SUFFICIENT INFORMATION", "AMBIGUOUS"}
_DATA_NO_DIRECTION = {"INCONCLUSIVE", "INVALID", "NOT_RUN"}

INSUFFICIENT_MESSAGE = "Not sufficient information"


def _document(value):
    """Return (orientation or "INSUFFICIENT", ambiguous flag)."""
    if value is None:
        return "INSUFFICIENT", False
    key = str(value).strip().upper()
    if key in _DOC_NO_ANSWER:
        return "INSUFFICIENT", key == "AMBIGUOUS"
    return normalize_orientation(key), False


def _data(value):
    """Accept a call string, a datacheck result dict, or None. Return (call, layout or None)."""
    layout = None
    if isinstance(value, dict):
        layout, value = value.get("layout"), value.get("call")
    if value is None:
        return "NOT_RUN", layout
    key = str(value).strip().upper()
    if key in _DATA_NO_DIRECTION:
        return key, layout
    return normalize_orientation(key), layout


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

    document: "FR" | "RF" | "UNSTRANDED" | "INSUFFICIENT" | "AMBIGUOUS" | None
              (fr-* library-type names are accepted too)
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

    if doc_known and data_known and doc == call:
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
        checks = [
            "Check for genomic DNA contamination, which adds reads in both directions.",
            "Run read quality checks (for example FastQC).",
            "Confirm that the reference and annotation match the species.",
        ]
        message = (f"Documents indicate {doc}, but the data check is inconclusive (dominant direction between "
                   f"60% and 90%). No settings are given automatically.")
    elif doc_known:  # data INVALID or NOT_RUN
        state, orientation, basis = "UNVERIFIED", doc, "documents"
        provisional = review = True
        if call == "INVALID":
            checks = ["Most reads could not be assigned; check that the reference, annotation and species match."]
        message = f"Documents indicate {doc}. This has not been verified against the data."
    elif data_known:
        state, orientation, basis = "DATA_ONLY", call, "data"
        message = f"The reads look {call}. The kit could not be identified from the notes."
    else:
        state = "INSUFFICIENT"
        message = INSUFFICIENT_MESSAGE

    return {
        "state": state,
        "document_orientation": doc,
        "document_ambiguous": ambiguous,
        "data_call": call,
        "layout": layout,
        "orientation": orientation,
        "settings_basis": basis,
        "verified_by_data": basis in ("documents and data", "data"),
        "provisional": provisional,
        "human_review_required": review,
        "message": message,
        "likely_causes": causes,
        "suggested_checks": checks,
        "settings": get_settings(orientation, layout) if orientation else None,
    }
