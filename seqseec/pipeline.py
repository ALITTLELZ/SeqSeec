# File: seqseec/pipeline.py
# Version: 0.2.0
# Last modified: 2026-11-19 (Track B)
# Change: Steps 2-3 wired in: kit registry retrieval + inference (LLM, or rules only with --llm none).
"""Run every step once and return one report. The command line is in seqseec/cli.py.

Steps run in STEP_ORDER. Each records a status in report["steps"][name]:
  extract    step 1, notes -> checked fields (LLM)      ok | skipped | error
  lookup     steps 2-3, notes -> registry -> orientation  ok | given | out_of_scope | skipped | error
  datacheck  step 4, reads -> data call (local tools)    ok | given | skipped | error
  reconcile  steps 5-6, decision table + settings       ok
  explain    step 7, plain explanation (LLM)            not_built

A failed step never stops the run: it counts as "no answer" and the decision
table handles it (for example, no document answer + an FR data call gives
DATA_ONLY). Errors are listed in the report, and report["ok"] is False.

Adding a parameter: add it to DEFAULTS here and to the matching argument group
in cli.py, then read it in the step that needs it. Adding a step: write a
_step_<name>(opts, report, stages) function and add it to STEP_ORDER / _STEPS.
Step 7 is a placeholder so its report slot already exists. Steps 2-3 use the
curated kit registry (seqseec.retrieve); with --llm none they use rules only.
"""
import os

from seqseec import __version__
from seqseec.datacheck import run_check_strandedness
from seqseec.extract import extract
from seqseec.infer import infer, infer_rules
from seqseec.llm import LLMError
from seqseec.reconcile import reconcile
from seqseec.settings import normalize_layout, normalize_orientation

LLM_MODES = ("api", "local", "none")

DEFAULTS = {
    # step 1
    "notes": None,              # notes text (not a path)
    "llm": "api",               # "api" | "local" | "none"
    "llm_config": None,         # from llm.get_config(); required unless llm == "none"
    # steps 2-3
    "expected": None,           # orientation the documents give, if the user already knows it
    # step 4
    "r1": None, "r2": None, "gtf": None, "transcripts": None,
    "nreads": 200000, "index_name": "kallisto_index", "tools_env": "seqseec-tools",
    "data_call": None,          # a data call from an earlier check; skips running the tools
    "layout": None,             # "PE" | "SE"; overrides the layout read from the notes
    # logs
    "audit_dir": "audit",
}

DEFAULT_STAGES = {"extract": extract, "infer": infer, "infer_rules": infer_rules,
                  "datacheck": run_check_strandedness}


def _options(options):
    unknown = set(options) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown option(s): {sorted(unknown)}")
    opts = {**DEFAULTS, **{k: v for k, v in options.items() if v is not None}}
    if opts["llm"] not in LLM_MODES:
        raise ValueError(f"llm must be one of {LLM_MODES}")
    if opts["llm"] != "none" and opts["notes"] and not opts["llm_config"]:
        raise ValueError("llm_config is required to read notes with an LLM")
    if opts["r2"] and not opts["r1"]:
        raise ValueError("r2 needs r1")
    if opts["r1"] and not (opts["gtf"] and opts["transcripts"]):
        raise ValueError("the data check needs gtf and transcripts as well as r1")
    if opts["r1"] and opts["data_call"]:
        raise ValueError("give either reads or a data call, not both")
    if opts["expected"]:
        opts["expected"] = normalize_orientation(opts["expected"])
    if opts["data_call"]:
        call = str(opts["data_call"]).strip().upper()
        opts["data_call"] = call if call in ("INCONCLUSIVE", "INVALID") else normalize_orientation(call)
    if opts["layout"]:
        opts["layout"] = normalize_layout(opts["layout"])
    return opts


# ---------- steps ----------

def _step_extract(opts, report, stages):
    if not opts["notes"]:
        return {"status": "skipped", "reason": "no notes given"}
    if opts["llm"] == "none":
        return {"status": "skipped", "reason": "LLM turned off (--llm none)"}
    try:
        out = stages["extract"](opts["notes"], config=opts["llm_config"],
                                audit_log=os.path.join(opts["audit_dir"], "payload_audit.jsonl"),
                                call_log=os.path.join(opts["audit_dir"], "llm_calls.jsonl"))
    except (LLMError, ValueError) as err:  # PayloadError is a ValueError
        return {"status": "error", "error": f"{type(err).__name__}: {err}"}
    return {"status": "ok", **out}


def _step_lookup(opts, report, stages):
    extracted = report["steps"]["extract"]
    if extracted.get("scope") == "OUT_OF_SCOPE":
        return {"status": "out_of_scope", "document_orientation": "OUT_OF_SCOPE",
                "reason": extracted.get("scope_reason")}
    if opts["expected"]:
        return {"status": "given", "document_orientation": opts["expected"], "reason": "given with --expected"}
    if not opts["notes"]:
        return {"status": "skipped", "document_orientation": None, "reason": "no notes given"}
    fields = extracted.get("fields") or {}
    try:
        if opts["llm"] == "none":
            out = stages["infer_rules"](opts["notes"], fields)
        else:
            out = stages["infer"](opts["notes"], fields, config=opts["llm_config"],
                                  audit_log=os.path.join(opts["audit_dir"], "payload_audit.jsonl"),
                                  call_log=os.path.join(opts["audit_dir"], "llm_calls.jsonl"))
    except (LLMError, ValueError) as err:  # PayloadError is a ValueError
        return {"status": "error", "document_orientation": None, "error": f"{type(err).__name__}: {err}"}
    return {"status": "ok", **out}


def _step_datacheck(opts, report, stages):
    if opts["data_call"]:
        return {"status": "given", "result": {"call": opts["data_call"], "layout": opts["layout"]}}
    if not opts["r1"]:
        return {"status": "skipped", "reason": "no reads given"}
    try:
        result = stages["datacheck"](opts["gtf"], opts["transcripts"], opts["r1"], opts["r2"],
                                     index_name=opts["index_name"], env=opts["tools_env"], nreads=opts["nreads"])
    except (RuntimeError, OSError, ValueError) as err:
        return {"status": "error", "error": f"{type(err).__name__}: {err}"}
    return {"status": "ok", "result": result}


def _step_reconcile(opts, report, stages):
    steps = report["steps"]
    notes_layout = (steps["extract"].get("fields") or {}).get("read_layout")
    data = steps["datacheck"].get("result")
    data_layout = (data or {}).get("layout")
    if data_layout and notes_layout and data_layout != notes_layout:
        report["warnings"].append(f"The notes say {notes_layout} but the reads are {data_layout}; "
                                  f"the reads' layout is used.")
    result = reconcile(steps["lookup"]["document_orientation"], data, layout=opts["layout"] or notes_layout)
    return {"status": "ok", **result}


def _step_explain(opts, report, stages):
    return {"status": "not_built", "reason": "Step 7 (plain-language explanation) is not built yet."}


STEP_ORDER = ("extract", "lookup", "datacheck", "reconcile", "explain")
_STEPS = {"extract": _step_extract, "lookup": _step_lookup, "datacheck": _step_datacheck,
          "reconcile": _step_reconcile, "explain": _step_explain}


# ---------- public API ----------

def run_pipeline(options, *, stages=None):
    """Run all steps and return the report dict.

    options: dict with keys from DEFAULTS (None values mean "use the default").
    stages:  optional replacements for the step functions in DEFAULT_STAGES (tests use fakes).
    Raises ValueError for bad options; step failures are recorded in the report instead.
    """
    opts = _options(options)
    stages = {**DEFAULT_STAGES, **(stages or {})}
    config = opts["llm_config"] if opts["llm"] != "none" else None
    report = {"seqseec_version": __version__, "llm": {"mode": opts["llm"],
                                                      "model": (config or {}).get("model")},
              "steps": {}, "warnings": []}
    for name in STEP_ORDER:
        report["steps"][name] = _STEPS[name](opts, report, stages)

    steps = report["steps"]
    report["result"] = {k: v for k, v in steps["reconcile"].items() if k != "status"}
    report["questions"] = steps["extract"].get("questions", [])
    report["warnings"] = steps["extract"].get("warnings", []) + report["warnings"]
    report["errors"] = [f"{name}: {step['error']}" for name, step in steps.items() if step["status"] == "error"]
    report["ok"] = not report["errors"]
    return report


# ---------- text report ----------

_STEP_LABELS = {"extract": "1 notes", "lookup": "2-3 kit lookup", "datacheck": "4 data check",
                "reconcile": "5-6 reconcile", "explain": "7 explain"}


def format_report(report):
    """Plain-text report for the terminal."""
    r, steps = report["result"], report["steps"]
    llm = report["llm"]
    lines = [f"SeqSeec {report['seqseec_version']} report   LLM: {llm['mode']}"
             + (f" ({llm['model']})" if llm["model"] else ""),
             "Steps: " + " | ".join(f"{_STEP_LABELS[n]}: {steps[n]['status'].replace('_', ' ')}"
                                    for n in STEP_ORDER), ""]
    lines.append(f"RESULT: {r['state']}")
    lines.append(f"  {r['message']}")
    lines.append(f"  documents: {r['document_orientation']}   data: {r['data_call']}   layout: {r['layout']}")
    if r["settings"]:
        lines.append(f"  orientation used: {r['orientation']} ({r['settings']['library_type']}), "
                     f"from {r['settings_basis']}")
        flags = [x for x, on in (("PROVISIONAL", r["provisional"]),
                                 ("HUMAN REVIEW REQUIRED", r["human_review_required"])) if on]
        if flags:
            lines.append("  " + ", ".join(flags))
        lines += ["", "Downstream settings:"]
        lines += [f"  {tool:<14}{t['setting']}" for tool, t in r["settings"]["tools"].items()]
    elif r["human_review_required"]:
        lines.append("  HUMAN REVIEW REQUIRED")
    for title, items in (("Likely causes", r["likely_causes"]), ("Suggested checks", r["suggested_checks"])):
        if items:
            lines += ["", f"{title}:"] + [f"  - {x}" for x in items]

    ext = steps["extract"]
    if ext["status"] == "ok":
        found = {k: v for k, v in ext["fields"].items() if v is not None}
        lines += ["", "From the notes (each with a verbatim quote):"]
        lines += [f"  {k:<17}{v}   <- \"{ext['evidence'].get(k, '')}\"" for k, v in found.items()] or ["  (nothing)"]
        lines += [f"  dropped {x['field']}: {x['reason']}" for x in ext["rejected"]]
    look = steps["lookup"]
    if look["status"] == "ok":
        lines += ["", f"From the kit registry (retrieval: {look['retrieval_method']}):"]
        if look.get("kit_name"):
            lines.append(f"  kit              {look['kit_name']}   <- \"{look['notes_quote']}\"")
            lines.append(f"  evidence         {look['evidence_type']}: {look['source_url']}")
            if look.get("citation"):
                lines.append(f"  vendor quote     \"{look['citation']['quote']}\"")
        lines.append(f"  document result  {look['document_orientation']}" + (f" ({look['reason']})" if look.get("reason") else ""))
        lines += [f"  rejected: {x}" for x in look.get("rejected", [])]
    if steps["explain"]["status"] == "not_built":
        lines += ["", f"Note: {steps['explain']['reason']}"]
    for title, items in (("Questions", report["questions"]), ("Warnings", report["warnings"]),
                         ("Errors", report["errors"])):
        if items:
            lines += ["", f"{title}:"] + [f"  - {x}" for x in items]
    return "\n".join(lines)
