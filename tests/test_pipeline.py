# File: tests/test_pipeline.py
# Version: 0.1.0
# Last modified: 2026-11-19 (XD)
# Change: Tests for run_pipeline(): step order and statuses, failures recorded not raised, layout rules, report text.
import functools
import json

import pytest

from seqseec.extract import extract
from seqseec.llm import LLMError
from seqseec.pipeline import DEFAULTS, STEP_ORDER, format_report, run_pipeline

NOTES = ("Total RNA from HeLa cells was poly(A)-selected and libraries were built with the "
         "NEBNext Ultra II Directional RNA Library Prep Kit, then sequenced 2x100 on a NovaSeq 6000.")
CONFIG = {"mode": "api", "api_key": "sk-test", "model": "deepseek-flash", "base_url": "https://api.example.test"}
FIELDS = {"kit_name": "NEBNext Ultra II Directional RNA Library Prep Kit", "read_layout": "PE"}


def fake_extract(scope="IN_SCOPE", fields=None, calls=None):
    def _extract(notes, **kw):
        if calls is not None:
            calls.append(kw)
        return {"fields": {**FIELDS, **(fields or {})}, "evidence": {}, "rejected": [], "scope": scope,
                "scope_reason": "long-read platform (PacBio Revio)" if scope == "OUT_OF_SCOPE" else None,
                "warnings": [], "questions": ["Which version?"] if scope == "IN_SCOPE" else [], "llm": {}}
    return _extract


def failing(error):
    def _stage(*args, **kw):
        raise error
    return _stage


def datacheck_returning(call="RF", layout="PE", calls=None):
    def _check(gtf, transcripts, r1, r2, **kw):
        if calls is not None:
            calls.append({"args": (gtf, transcripts, r1, r2), **kw})
        return {"layout": layout, "failed_fraction": 0.02, "forward_fraction": 0.03, "reverse_fraction": 0.95,
                "forward_share": 0.03, "reverse_share": 0.97, "call": call, "reason": "x",
                "tool": "how_are_we_stranded_here@e6ce74d", "nreads_requested": 200000}
    return _check


READS = {"r1": "R1.fq.gz", "r2": "R2.fq.gz", "gtf": "g.gtf", "transcripts": "t.fa"}


def run(stages=None, **options):
    return run_pipeline({"llm_config": CONFIG, **options}, stages=stages)


# ---------- structure ----------

def test_every_step_reported_in_order():
    report = run(llm="none", expected="RF", data_call="RF")
    assert tuple(report["steps"]) == STEP_ORDER
    assert {n: s["status"] for n, s in report["steps"].items()} == {
        "extract": "skipped", "lookup": "given", "datacheck": "given", "reconcile": "ok", "explain": "not_built"}
    assert report["result"]["state"] == "CONCORDANT" and report["ok"] is True
    json.dumps(report)  # the whole report is JSON-serialisable


def test_bad_options_raise():
    for bad in ({"colour": "red"}, {"llm": "cloud"}, {"r2": "R2.fq"}, {"r1": "R1.fq"},
                {"data_call": "SIDEWAYS"}, {"expected": "up"}, {**READS, "data_call": "RF"},
                {"notes": NOTES, "llm_config": None}):
        with pytest.raises(ValueError):
            run_pipeline(bad)


def test_defaults_cover_every_cli_option():
    from seqseec.cli import build_parser
    run_parser = build_parser()._subparsers._group_actions[0].choices["run"]
    dests = {a.dest for a in run_parser._actions} - {"help", "model", "base_url", "env_file", "format", "out"}
    assert dests <= set(DEFAULTS), dests - set(DEFAULTS)


# ---------- steps 1 -> 2-3 ----------

def test_notes_without_kit_lookup_give_data_only():
    report = run({"extract": fake_extract()}, notes=NOTES, data_call="RF")
    assert report["steps"]["extract"]["status"] == "ok"
    assert report["steps"]["lookup"]["status"] == "not_built"
    assert report["result"]["state"] == "DATA_ONLY" and report["questions"] == ["Which version?"]


def test_expected_with_notes_and_data():
    report = run({"extract": fake_extract()}, notes=NOTES, expected="fr-firststrand", data_call="FR")
    assert report["result"]["state"] == "CONFLICT" and report["result"]["human_review_required"]


def test_out_of_scope_wins_over_expected():
    report = run({"extract": fake_extract(scope="OUT_OF_SCOPE")}, notes=NOTES, expected="RF", data_call="RF")
    assert report["steps"]["lookup"]["status"] == "out_of_scope"
    assert report["result"]["state"] == "OUT_OF_SCOPE" and report["result"]["settings"] is None


def test_llm_none_never_calls_extract():
    report = run({"extract": failing(AssertionError("must not be called"))}, notes=NOTES, llm="none",
                 data_call="UNSTRANDED")
    assert report["steps"]["extract"]["status"] == "skipped" and report["llm"]["model"] is None


@pytest.mark.parametrize("error", [LLMError("could not reach the LLM API: refused", retryable=True),
                                   ValueError("LLM output must be a JSON object")])
def test_extract_failure_recorded_and_run_continues(error):
    report = run({"extract": failing(error)}, notes=NOTES, data_call="RF")
    assert report["steps"]["extract"]["status"] == "error" and report["ok"] is False
    assert report["errors"][0].startswith("extract: ")
    assert report["result"]["state"] == "DATA_ONLY"


def test_real_extract_with_fake_api_writes_logs_to_audit_dir(tmp_path):
    answer = {"fields": {"kit_name": FIELDS["kit_name"], "read_layout": "PE"},
              "evidence": {"kit_name": FIELDS["kit_name"], "read_layout": "2x100"}}

    def transport(url, headers, body, timeout):
        return {"id": "r", "model": "m", "choices": [{"finish_reason": "stop",
                                                       "message": {"content": json.dumps(answer)}}]}
    stage = functools.partial(extract, transport=transport)
    report = run({"extract": stage}, notes=NOTES, expected="RF", data_call="RF", audit_dir=str(tmp_path / "logs"))
    assert report["steps"]["extract"]["fields"]["read_layout"] == "PE"
    assert report["result"]["state"] == "CONCORDANT"
    assert (tmp_path / "logs" / "payload_audit.jsonl").exists() and (tmp_path / "logs" / "llm_calls.jsonl").exists()


def test_notes_with_reads_are_refused_not_sent():
    report = run({"extract": functools.partial(extract, transport=failing(AssertionError("sent")))},
                 notes=NOTES + " " + "ACGT" * 10, data_call="RF")
    assert report["steps"]["extract"]["status"] == "error" and "PayloadError" in report["errors"][0]


# ---------- step 4 ----------

def test_datacheck_gets_the_read_options():
    calls = []
    report = run({"datacheck": datacheck_returning(calls=calls)}, llm="none", expected="RF", nreads=5000, **READS)
    assert calls[0]["args"] == ("g.gtf", "t.fa", "R1.fq.gz", "R2.fq.gz")
    assert calls[0]["nreads"] == 5000 and calls[0]["env"] == "seqseec-tools"
    assert report["steps"]["datacheck"]["status"] == "ok" and report["result"]["state"] == "CONCORDANT"


def test_datacheck_failure_gives_unverified():
    report = run({"datacheck": failing(RuntimeError("check_strandedness failed (exit 1)"))},
                 llm="none", expected="FR", **READS)
    assert report["steps"]["datacheck"]["status"] == "error"
    assert report["result"]["state"] == "UNVERIFIED" and report["result"]["provisional"]


def test_no_reads_skips_datacheck():
    report = run(llm="none", expected="UNSTRANDED")
    assert report["steps"]["datacheck"]["status"] == "skipped" and report["result"]["state"] == "UNVERIFIED"


# ---------- layout ----------

def test_reads_layout_wins_over_notes_with_warning():
    report = run({"extract": fake_extract(), "datacheck": datacheck_returning(layout="SE")},
                 notes=NOTES, expected="RF", **{**READS, "r2": None})
    assert report["result"]["layout"] == "SE"
    assert report["result"]["settings"]["tools"]["Salmon"]["setting"] == "-l SR"
    assert any("notes say PE" in w for w in report["warnings"])


def test_notes_layout_used_when_no_reads():
    report = run({"extract": fake_extract(fields={"read_layout": "SE"})}, notes=NOTES, expected="FR")
    assert report["result"]["layout"] == "SE"


def test_layout_option_overrides_notes():
    report = run({"extract": fake_extract(fields={"read_layout": "SE"})}, notes=NOTES, expected="FR", layout="pe")
    assert report["result"]["layout"] == "PE"


# ---------- text report ----------

def test_text_report_has_the_essentials():
    text = format_report(run({"extract": fake_extract()}, notes=NOTES, expected="RF", data_call="FR"))
    for needle in ("RESULT: CONFLICT", "HUMAN REVIEW REQUIRED", "featureCounts", "-s 1", "Likely causes",
                   "R1 and R2 files swapped", "Questions", "Which version?", "2-3 kit lookup: given"):
        assert needle in text, needle


def test_text_report_says_what_is_not_built():
    text = format_report(run(llm="none", data_call="INCONCLUSIVE"))
    assert "RESULT: INSUFFICIENT" in text and "Steps 2-3" in text and "Step 7" in text
