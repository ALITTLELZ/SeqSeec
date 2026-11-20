# File: seqseec/payload.py
# Version: 0.1.1
# Last modified: 2026-11-20 (Track B)
# Change: Removed references to the retired team plan document (comments only).
"""The only gate between SeqSeec and the LLM (isolation is enforced by code).

Every LLM call (step 1 extract, step 3 infer, step 7 explain) must get its input
from build_payload(). It:

1. Accepts only named parts, and only the parts allowed for that task:
     extract  notes
     infer    notes, fields, chunks
     explain  fields, inference, data_summary, reconcile, chunks
2. Allow-lists the keys of structured parts (data_summary from datacheck,
   reconcile from reconcile, each document chunk). Unknown keys are refused,
   so a new field (such as a file path) cannot slip through unnoticed.
3. Scans every string for read data and secrets and refuses the whole payload
   if it finds any:
     * a run of MIN_SEQUENCE_RUN or more nucleotides (A/C/G/T/N), which is
       longer than typical primers and indexes but shorter than any read
       (not applied to chunks, which come from the curated public library
       and can quote full adapter sequences);
     * a FASTQ record (@header / sequence / + lines);
     * an API key ("sk-...");
     * any single string over MAX_TEXT_CHARS (for example a pasted file).
4. Appends every result to a JSONL audit log: the full payload when built,
   or only the task and the reason (never the offending content) when blocked.

It fails closed: anything it does not recognise is refused, never dropped.
check_audit_log() re-scans a log after a run.
"""
import datetime
import hashlib
import json
import os
import re

PAYLOAD_VERSION = 1
DEFAULT_AUDIT_LOG = os.path.join("audit", "payload_audit.jsonl")

TASK_PARTS = {
    "extract": frozenset({"notes"}),
    "infer": frozenset({"notes", "fields", "chunks"}),
    "explain": frozenset({"fields", "inference", "data_summary", "reconcile", "chunks"}),
}
REQUIRED_PARTS = {
    "extract": frozenset({"notes"}),
    "infer": frozenset({"notes"}),
    "explain": frozenset({"reconcile"}),
}

# Keys produced by seqseec.datacheck.run_check_strandedness (numbers and labels only).
DATA_SUMMARY_KEYS = frozenset({
    "layout", "failed_fraction", "forward_fraction", "reverse_fraction", "forward_share", "reverse_share",
    "call", "reason", "tool", "nreads_requested",
})
# Keys produced by seqseec.reconcile.reconcile.
RECONCILE_KEYS = frozenset({
    "state", "document_orientation", "document_ambiguous", "data_call", "layout", "orientation",
    "settings_basis", "documents_confirmed_by_data", "provisional", "human_review_required", "message",
    "likely_causes", "suggested_checks", "settings",
})
CHUNK_REQUIRED_KEYS = frozenset({"chunk_id", "text"})
CHUNK_OPTIONAL_KEYS = frozenset({"kit", "version", "vendor", "source", "page", "date", "score"})

MIN_SEQUENCE_RUN = 30
MAX_TEXT_CHARS = 50_000

_SEQUENCE = re.compile(rf"[ACGTN]{{{MIN_SEQUENCE_RUN},}}", re.IGNORECASE)
_FASTQ = re.compile(r"^@[^\n]*\r?\n[ACGTN]+\r?\n\+", re.IGNORECASE | re.MULTILINE)
_SECRET = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")


class PayloadError(ValueError):
    """Raised when a payload is refused. The message never contains the refused content."""


# ---------- content scanning ----------

def _strings(obj, where):
    """Yield (location, string) for every string in obj, including dict keys."""
    if isinstance(obj, str):
        yield where, obj
    elif obj is None or isinstance(obj, (bool, int, float)):
        return
    elif isinstance(obj, dict):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise PayloadError(f"{where}: dictionary keys must be strings")
            yield f"{where} (key)", key
            yield from _strings(value, f"{where}.{key}")
    elif isinstance(obj, (list, tuple)):
        for i, value in enumerate(obj):
            yield from _strings(value, f"{where}[{i}]")
    else:
        raise PayloadError(f"{where}: unsupported type {type(obj).__name__}")


def find_problems(obj, where, check_sequences=True):
    """Return a list of problems in obj, each naming the location but not the content."""
    problems = []
    for loc, text in _strings(obj, where):
        if len(text) > MAX_TEXT_CHARS:
            problems.append(f"{loc}: text longer than {MAX_TEXT_CHARS} characters")
        if check_sequences and _SEQUENCE.search(text):
            problems.append(f"{loc}: nucleotide run of {MIN_SEQUENCE_RUN}+ characters (possible read sequence)")
        if _FASTQ.search(text):
            problems.append(f"{loc}: FASTQ record")
        if _SECRET.search(text):
            problems.append(f"{loc}: API key")
    return problems


# ---------- per-part validation ----------

_SAFE_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,40}")


def _show_key(key):
    """Key name for an error message, or a placeholder if it could carry content."""
    return key if isinstance(key, str) and _SAFE_KEY.fullmatch(key) else "<unprintable key>"


def _json_copy(value, where):
    try:
        return json.loads(json.dumps(value))
    except (TypeError, ValueError):
        raise PayloadError(f"{where}: not JSON-serialisable") from None


def _check_keys(d, allowed, where, required=frozenset()):
    if not isinstance(d, dict):
        raise PayloadError(f"{where}: must be a dict")
    unknown = sorted(_show_key(k) for k in set(d) - allowed)
    if unknown:
        raise PayloadError(f"{where}: keys not on the allow-list: {unknown}")
    missing = sorted(required - set(d))
    if missing:
        raise PayloadError(f"{where}: missing required keys: {missing}")


def _clean_notes(value):
    if not isinstance(value, str) or not value.strip():
        raise PayloadError("notes: must be non-empty text")
    return value


def _clean_json_object(name):
    def clean(value):
        if not isinstance(value, dict):
            raise PayloadError(f"{name}: must be a dict (JSON object from an earlier step)")
        return _json_copy(value, name)
    return clean


def _clean_data_summary(value):
    _check_keys(value, DATA_SUMMARY_KEYS, "data_summary", required=frozenset({"call"}))
    for key, v in value.items():
        if not (v is None or isinstance(v, (str, bool, int, float))):
            raise PayloadError(f"data_summary.{key}: must be a number, text or null")
    return dict(value)


def _clean_reconcile(value):
    _check_keys(value, RECONCILE_KEYS, "reconcile", required=frozenset({"state"}))
    return _json_copy(value, "reconcile")


def _clean_chunks(value):
    if not isinstance(value, (list, tuple)):
        raise PayloadError("chunks: must be a list")
    out = []
    for i, chunk in enumerate(value):
        _check_keys(chunk, CHUNK_REQUIRED_KEYS | CHUNK_OPTIONAL_KEYS, f"chunks[{i}]", CHUNK_REQUIRED_KEYS)
        out.append(_json_copy(chunk, f"chunks[{i}]"))
    return out


_CLEANERS = {
    "notes": _clean_notes,
    "fields": _clean_json_object("fields"),
    "inference": _clean_json_object("inference"),
    "data_summary": _clean_data_summary,
    "reconcile": _clean_reconcile,
    "chunks": _clean_chunks,
}


# ---------- audit log ----------

def _audit(path, record):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    record = {"logged_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), **record}
    with open(path, "a", encoding="utf8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _canonical(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


# ---------- public API ----------

def build_payload(task, *, notes=None, fields=None, chunks=None, inference=None, data_summary=None,
                  reconcile=None, audit_log=DEFAULT_AUDIT_LOG):
    """Build, check and log the payload for one LLM call.

    Returns {"payload": {"payload_version", "task", "parts"}, "sha256": hex digest of the payload}.
    Raises PayloadError (after logging a "blocked" record) if anything is not allowed.
    """
    given = {name: value for name, value in {
        "notes": notes, "fields": fields, "chunks": chunks, "inference": inference,
        "data_summary": data_summary, "reconcile": reconcile}.items() if value is not None}
    try:
        if task not in TASK_PARTS:
            raise PayloadError(f"unknown task (allowed: {sorted(TASK_PARTS)})")
        not_allowed = sorted(set(given) - TASK_PARTS[task])
        if not_allowed:
            raise PayloadError(f"parts not allowed for task '{task}': {not_allowed}")
        missing = sorted(REQUIRED_PARTS[task] - set(given))
        if missing:
            raise PayloadError(f"task '{task}' is missing required parts: {missing}")
        parts = {name: _CLEANERS[name](value) for name, value in given.items()}
        problems = []
        for name, value in parts.items():
            problems += find_problems(value, name, check_sequences=(name != "chunks"))
        if problems:
            raise PayloadError("; ".join(problems))
    except PayloadError as err:
        _audit(audit_log, {"status": "blocked", "task": task if task in TASK_PARTS else "unknown",
                           "reason": str(err)})
        raise

    payload = {"payload_version": PAYLOAD_VERSION, "task": task, "parts": parts}
    digest = hashlib.sha256(_canonical(payload).encode("utf8")).hexdigest()
    _audit(audit_log, {"status": "built", "task": task, "sha256": digest, "payload": payload})
    return {"payload": payload, "sha256": digest}


def check_audit_log(path=DEFAULT_AUDIT_LOG):
    """Re-scan an audit log with the same rules. Returns a list of problems (empty = clean)."""
    problems = []
    with open(path, encoding="utf8") as f:
        for n, line in enumerate(f, 1):
            record = json.loads(line)
            where = f"line {n}"
            if record.get("status") == "built":
                for name, value in record["payload"]["parts"].items():
                    problems += find_problems(value, f"{where} {name}", check_sequences=(name != "chunks"))
            else:
                problems += find_problems(record.get("reason", ""), f"{where} reason")
    return problems
