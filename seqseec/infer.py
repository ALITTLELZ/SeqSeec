# File: seqseec/infer.py
# Version: 0.1.0
# Last modified: 2026-11-19 (Track B)
# Change: Step 3 document inference: rules-only, LLM with retrieval (citation-checked), and no-retrieval baseline.
"""Step 3: from the notes and the retrieved registry entries, the orientation the documents give.

Three ways to run it, all returning the same result shape:

  infer_rules(notes, fields)            no LLM. One alias candidate (or several that agree)
                                        -> its orientation; candidates that disagree -> AMBIGUOUS;
                                        otherwise INSUFFICIENT. Used with --llm none.
  infer(notes, fields, config=...)      LLM chooses among retrieved candidates (prompt infer_v1).
                                        Code then checks the answer (see interpret()) and looks up
                                        the orientation in the registry; the LLM never states it.
  infer_without_retrieval(...)          evaluation baseline: same model, no documents
                                        (prompt infer_noretrieval_v1); its answer is not checkable.

result["document_orientation"] is FR | RF | UNSTRANDED | AMBIGUOUS | INSUFFICIENT and goes
straight into seqseec.reconcile.
"""
import re

from seqseec.extract import load_prompt
from seqseec.llm import DEFAULT_CALL_LOG, call_llm
from seqseec.payload import DEFAULT_AUDIT_LOG, build_payload
from seqseec.retrieve import load_aliases, load_registry, retrieve

PROMPT_ID = "infer_v1"
BASELINE_PROMPT_ID = "infer_noretrieval_v1"
DECISIONS = ("KIT", "CHEMISTRY", "AMBIGUOUS", "INSUFFICIENT")
MIN_CITATION_CHARS = 15
# DeepSeek spends most tokens on reasoning; 2000 cut off a baseline answer on 2026-11-19 (1465 reasoning tokens).
INFER_MAX_TOKENS = 4000


def _normalize(text):
    text = str(text).translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-"}))
    return re.sub(r"\s+", " ", text).strip().casefold()


def _result(orientation, retrieval, **extra):
    base = {"document_orientation": orientation, "decision": None, "kit_id": None, "kit_name": None,
            "evidence_type": None, "source_url": None, "notes_quote": None, "citation": None,
            "candidates": retrieval["candidates"], "retrieval_method": retrieval["method"],
            "rejected": [], "reason": None}
    base.update(extra)
    return base


def _entry_fields(registry, kit_id):
    row = registry[kit_id]
    return {"kit_id": kit_id, "kit_name": row["kit_name"], "evidence_type": row["evidence"],
            "source_url": row["source_url"]}


def _rules(retrieval, registry):
    """Deterministic decision from the retrieval result alone."""
    cands = retrieval["candidates"]
    if retrieval["method"] != "alias" or not cands:
        return _result("INSUFFICIENT", retrieval, decision="INSUFFICIENT",
                       reason="No kit or chemistry from the registry is named in the notes.")
    orientations = {c["orientation"] for c in cands}
    if len(orientations) > 1:
        return _result("AMBIGUOUS", retrieval, decision="AMBIGUOUS",
                       reason="The notes match registry entries that differ in orientation: "
                              + ", ".join(c["kit_id"] for c in cands) + ".")
    orientation = orientations.pop()
    if len(cands) == 1:
        c = cands[0]
        return _result(orientation, retrieval, decision="CHEMISTRY" if c["kind"] == "chemistry" else "KIT",
                       notes_quote=c["alias"], reason=f"The notes name {c['alias']!r}.",
                       **_entry_fields(registry, c["kit_id"]))
    return _result(orientation, retrieval, decision="KIT",
                   reason="The notes match several registry entries that share this orientation: "
                          + ", ".join(c["kit_id"] for c in cands) + ".")


def infer_rules(notes, fields=None, *, registry=None):
    registry = registry or load_registry()
    return _rules(retrieve(notes, fields, registry=registry), registry)


def interpret(notes, output, retrieval, registry, aliases=None):
    """Check one LLM answer. Pure function. Any failed check gives INSUFFICIENT with the reason in rejected."""
    aliases = aliases or load_aliases(registry)
    chunks = {c["chunk_id"]: c for c in retrieval["chunks"]}
    cand = {c["kit_id"]: c for c in retrieval["candidates"]}

    def reject(why):
        return _result("INSUFFICIENT", retrieval, decision="INSUFFICIENT", rejected=[why],
                       reason="The LLM answer failed a check, so no document orientation is given.")

    if not isinstance(output, dict) or output.get("decision") not in DECISIONS:
        return reject("answer is not a JSON object with a known decision")
    decision = output["decision"]
    reason = str(output.get("reason") or "")[:300]

    if decision == "INSUFFICIENT":
        return _result("INSUFFICIENT", retrieval, decision=decision, reason=reason)
    if decision == "AMBIGUOUS":
        orientations = {c["orientation"] for c in retrieval["candidates"]}
        if len(orientations) == 1:  # candidates agree, so the orientation is known even if the kit is not
            return _result(orientations.pop(), retrieval, decision="KIT", reason=reason +
                           " (all candidates share this orientation)")
        return _result("AMBIGUOUS", retrieval, decision=decision, reason=reason)

    kit_id = output.get("kit_id")
    if kit_id not in chunks:
        return reject("kit_id is not one of the retrieved candidates")
    notes_quote = output.get("notes_quote")
    if not isinstance(notes_quote, str) or not notes_quote.strip():
        return reject("no quote from the notes")
    if _normalize(notes_quote) not in _normalize(notes):
        return reject("notes_quote not found in the notes")
    citation = output.get("citation")
    if not isinstance(citation, dict) or citation.get("chunk_id") != kit_id:
        return reject("citation must come from the chosen entry")
    quote = citation.get("quote")
    if not isinstance(quote, str) or len(quote.strip()) < MIN_CITATION_CHARS:
        return reject("citation quote missing or too short")
    if _normalize(quote) not in _normalize(chunks[kit_id]["text"]):
        return reject("citation quote not found in the chosen entry")

    # The notes quote must point to the chosen kit and not equally to a kit with another orientation.
    sub = retrieve(notes_quote, registry=registry, aliases=aliases)
    if sub["method"] == "alias":
        sub_ids = {c["kit_id"] for c in sub["candidates"]}
        if kit_id not in sub_ids:
            return reject("notes_quote does not name the chosen entry")
        if len({c["orientation"] for c in sub["candidates"]}) > 1:
            return _result("AMBIGUOUS", retrieval, decision="AMBIGUOUS",
                           reason="The quoted name fits several kits that differ in orientation.",
                           rejected=["notes_quote does not tell the candidates apart"])
    elif cand[kit_id]["matched_by"] == "alias":
        return reject("notes_quote does not name the chosen entry")

    return _result(registry[kit_id]["orientation"], retrieval, decision=decision, reason=reason,
                   notes_quote=notes_quote.strip(), citation={"chunk_id": kit_id, "quote": quote.strip()},
                   **_entry_fields(registry, kit_id))


def infer(notes, fields=None, *, prompt_id=PROMPT_ID, audit_log=DEFAULT_AUDIT_LOG, call_log=DEFAULT_CALL_LOG,
          registry=None, **llm_options):
    """Retrieve candidates, ask the LLM to choose, check the answer. No candidates -> INSUFFICIENT, no call."""
    registry = registry or load_registry()
    aliases = load_aliases(registry)
    retrieval = retrieve(notes, fields, registry=registry, aliases=aliases)
    rules = _rules(retrieval, registry)
    if not retrieval["chunks"]:
        out = dict(rules)
        out["llm"] = None
        out["rules_orientation"] = rules["document_orientation"]
        return out
    llm_options.setdefault("max_tokens", INFER_MAX_TOKENS)
    built = build_payload("infer", notes=notes, fields=_clean_fields(fields), chunks=retrieval["chunks"],
                          audit_log=audit_log)
    result = call_llm(built, load_prompt(prompt_id), prompt_id, call_log=call_log, **llm_options)
    out = interpret(notes, result["output"], retrieval, registry, aliases)
    out["rules_orientation"] = rules["document_orientation"]
    rec = result["record"]
    out["llm"] = {key: rec.get(key) for key in
                  ("prompt_id", "payload_sha256", "requested_model", "response_model", "attempt")}
    return out


def _clean_fields(fields):
    return {k: v for k, v in (fields or {}).items() if v is not None} or None


def infer_without_retrieval(notes, fields=None, *, prompt_id=BASELINE_PROMPT_ID, audit_log=DEFAULT_AUDIT_LOG,
                            call_log=DEFAULT_CALL_LOG, **llm_options):
    """Evaluation baseline. Returns {"document_orientation", "kit", "reason", "llm"}; nothing is checked."""
    llm_options.setdefault("max_tokens", INFER_MAX_TOKENS)
    built = build_payload("infer", notes=notes, fields=_clean_fields(fields), audit_log=audit_log)
    result = call_llm(built, load_prompt(prompt_id), prompt_id, call_log=call_log, **llm_options)
    output = result["output"] if isinstance(result["output"], dict) else {}
    orientation = str(output.get("orientation") or "").strip().upper()
    rec = result["record"]
    return {"document_orientation": orientation if orientation in ("FR", "RF", "UNSTRANDED") else "INSUFFICIENT",
            "kit": output.get("kit"), "reason": str(output.get("reason") or "")[:300],
            "llm": {key: rec.get(key) for key in ("prompt_id", "requested_model", "response_model", "attempt")}}
