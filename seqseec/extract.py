# File: seqseec/extract.py
# Version: 0.1.0
# Last modified: 2026-11-19 (XD)
# Change: Step 1 field extraction: LLM reads notes (prompt extract_v1); code checks quotes, decides scope, asks questions.
"""Step 1: extract library-prep facts from lab notes.

The LLM only reads text (plan §3). Code then checks and decides:
  * every non-null field needs a quote that appears verbatim in the notes
    (ignoring case, spacing and curly quotes); a field without one is dropped
    and listed in "rejected", so the LLM cannot add facts the notes do not state;
  * fixed-choice fields (read_layout, rna_selection, library_type) must be one
    of the allowed values;
  * scope (plan §2) is decided by code from the checked platform and
    library_type: Nanopore, PacBio or single-cell -> OUT_OF_SCOPE;
  * when key facts are missing, code writes the questions to ask the user.

extract(notes) runs payload.build_payload -> llm.call_llm -> interpret().
interpret() holds all the checking logic and can be tested without an LLM.
"""
import os
import re

from seqseec.llm import DEFAULT_CALL_LOG, call_llm
from seqseec.payload import DEFAULT_AUDIT_LOG, build_payload
from seqseec.settings import normalize_layout

PROMPT_ID = "extract_v1"
PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts")

FIELDS = ("kit_name", "kit_version", "vendor", "chemistry", "strand_statement", "rna_selection",
          "read_layout", "platform", "library_type", "organism")
MAX_VALUE_CHARS = 200

_RNA_SELECTION = {"POLYA": "polyA", "POLY(A)": "polyA", "POLY A": "polyA",
                  "RRNA DEPLETION": "rRNA depletion", "RIBODEPLETION": "rRNA depletion",
                  "RIBO DEPLETION": "rRNA depletion", "OTHER": "other"}
_LIBRARY_TYPE = {"BULK": "bulk", "SINGLE CELL": "single-cell", "SINGLE NUCLEUS": "single-cell"}

_LONG_READ = re.compile(r"nanopore|\bONT\b|minion|gridion|promethion|pacbio|pacific biosciences|"
                        r"\bsequel\b|\brevio\b|iso-?seq|kinnex", re.IGNORECASE)
_SINGLE_CELL = re.compile(r"single[- ]?(cell|nucleus)|\bsc(rna|nrna)?-?seq\b|\bsn(rna)?-?seq\b|10x genomics|"
                          r"\bchromium\b", re.IGNORECASE)
TESTED_ORGANISMS = re.compile(r"\b(human|homo sapiens|mouse|mus musculus|murine)\b", re.IGNORECASE)


def load_prompt(prompt_id=PROMPT_ID):
    """Read prompts/<prompt_id>.md and drop its leading <!-- header --> comment."""
    with open(os.path.join(PROMPTS_DIR, f"{prompt_id}.md"), encoding="utf8") as f:
        text = f.read()
    return re.sub(r"\A\s*<!--.*?-->\s*", "", text, flags=re.DOTALL)


def _normalize_text(text):
    """Case-, space- and quote-insensitive form used to match quotes against the notes."""
    text = text.translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'",
                                         "–": "-", "—": "-"}))
    return re.sub(r"\s+", " ", text).strip().casefold()


def _canon(value):
    return re.sub(r"[\s_-]+", " ", value.strip().upper())


def _clean_value(field, value):
    """Return (clean value, None) or (None, reason)."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None, "value must be text"
    value = str(value).strip()
    if not value:
        return None, None
    if len(value) > MAX_VALUE_CHARS:
        return None, f"value longer than {MAX_VALUE_CHARS} characters"
    if field == "read_layout":
        try:
            return normalize_layout(value), None
        except ValueError:
            return None, "read_layout must be PE or SE"
    if field == "rna_selection":
        key = _canon(value)
        return (_RNA_SELECTION[key], None) if key in _RNA_SELECTION else (None, "rna_selection not an allowed value")
    if field == "library_type":
        key = _canon(value)
        return (_LIBRARY_TYPE[key], None) if key in _LIBRARY_TYPE else (None, "library_type not an allowed value")
    return value, None


def _scope(fields):
    if fields["platform"] and _LONG_READ.search(fields["platform"]):
        return "OUT_OF_SCOPE", f"long-read platform ({fields['platform']})"
    if fields["library_type"] == "single-cell":
        return "OUT_OF_SCOPE", "single-cell library"
    for name in ("platform", "kit_name"):
        if fields[name] and _SINGLE_CELL.search(fields[name]):
            return "OUT_OF_SCOPE", f"single-cell library ({fields[name]})"
    return "IN_SCOPE", None


def _questions(fields):
    questions = []
    if not (fields["kit_name"] or fields["chemistry"] or fields["strand_statement"]):
        questions.append("Which library-prep kit (name and version) was used, or was the library stranded?")
    elif fields["kit_name"] and not fields["kit_version"]:
        questions.append(f"Which version of {fields['kit_name']} was used? "
                         f"Some kits changed read orientation between versions.")
    if not fields["read_layout"]:
        questions.append("Were the reads paired-end or single-end?")
    return questions


def interpret(notes, output):
    """Check one LLM answer against the notes. Pure function; no LLM call.

    Returns {"fields", "evidence", "rejected", "scope", "scope_reason", "warnings", "questions"}.
    """
    if not isinstance(output, dict) or not isinstance(output.get("fields"), dict):
        raise ValueError("LLM output must be a JSON object with a 'fields' object")
    raw_fields = output["fields"]
    raw_evidence = output.get("evidence") if isinstance(output.get("evidence"), dict) else {}
    notes_norm = _normalize_text(notes)

    fields, evidence, rejected = dict.fromkeys(FIELDS), {}, []
    for name in sorted(set(raw_fields) - set(FIELDS)):
        rejected.append({"field": str(name)[:40], "reason": "not a known field"})
    for name in FIELDS:
        value, problem = _clean_value(name, raw_fields.get(name)) if raw_fields.get(name) is not None else (None, None)
        if problem:
            rejected.append({"field": name, "reason": problem})
            continue
        if value is None:
            continue
        quote = raw_evidence.get(name)
        if not isinstance(quote, str) or not quote.strip():
            rejected.append({"field": name, "reason": "no supporting quote"})
            continue
        if _normalize_text(quote) not in notes_norm:
            rejected.append({"field": name, "reason": "quote not found in the notes"})
            continue
        fields[name], evidence[name] = value, quote.strip()

    scope, scope_reason = _scope(fields)
    warnings = []
    if fields["organism"] and not TESTED_ORGANISMS.search(fields["organism"]):
        warnings.append(f"Organism '{fields['organism']}' may be outside the tested scope (human, mouse).")
    return {"fields": fields, "evidence": evidence, "rejected": rejected, "scope": scope,
            "scope_reason": scope_reason, "warnings": warnings,
            "questions": _questions(fields) if scope == "IN_SCOPE" else []}


def extract(notes, *, prompt_id=PROMPT_ID, audit_log=DEFAULT_AUDIT_LOG, call_log=DEFAULT_CALL_LOG, **llm_options):
    """Run step 1 on one set of notes.

    llm_options are passed to llm.call_llm (e.g. config, transport, max_tokens).
    Returns interpret()'s result plus "llm": prompt ID, payload hash, model IDs and attempt count.
    Raises payload.PayloadError if the notes are refused, llm.LLMError if the call fails,
    and ValueError if the answer does not have the expected shape.
    """
    built = build_payload("extract", notes=notes, audit_log=audit_log)
    result = call_llm(built, load_prompt(prompt_id), prompt_id, call_log=call_log, **llm_options)
    out = interpret(notes, result["output"])
    rec = result["record"]
    out["llm"] = {key: rec.get(key) for key in
                  ("prompt_id", "payload_sha256", "requested_model", "response_model", "attempt")}
    return out
