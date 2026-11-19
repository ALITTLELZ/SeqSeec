# File: tests/test_payload.py
# Version: 0.1.0
# Last modified: 2026-11-19 (XD)
# Change: Tests for the LLM payload gate: allow-lists, content guards, audit log, no reads in the log.
import json
import random

import pytest

from seqseec.datacheck import call_orientation, parse_infer_experiment
from seqseec.payload import (DATA_SUMMARY_KEYS, MIN_SEQUENCE_RUN, RECONCILE_KEYS, PayloadError, build_payload,
                             check_audit_log)
from seqseec.reconcile import reconcile

RNG = random.Random(535)
READ = "".join(RNG.choice("ACGT") for _ in range(100))          # a realistic 100-nt read
FASTQ_RECORD = f"@toy_1/1\n{READ}\n+\n{'I' * 100}\n"
PRIMER = "AGATCGGAAGAGCACACGTCTGAACTCCAG"[:25]                  # 25 nt: below the threshold
ADAPTER = "AGATCGGAAGAGCACACGTCTGAACTCCAGTCACATCACGATCTCGTATGCCGTCTTCTGCTTG"  # full-length, quoted in kit docs
API_KEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0"

NOTES = "Libraries were prepared with the TruSeq Stranded mRNA kit and sequenced 2x100 on a NovaSeq."

PE_RF = """This is PairEnd Data
Fraction of reads failed to determine: 0.0100
Fraction of reads explained by "1++,1--,2+-,2-+": 0.0200
Fraction of reads explained by "1+-,1-+,2++,2--": 0.9700
"""


def data_summary():
    """A data summary exactly as run_check_strandedness returns it."""
    out = call_orientation(parse_infer_experiment(PE_RF))
    out.update(tool="how_are_we_stranded_here@e6ce74d", nreads_requested=200000)
    return out


def chunk(text="dUTP marks the second strand, so read 1 is antisense.", **extra):
    return {"chunk_id": "truseq-stranded-mrna-p12-c3", "kit": "TruSeq Stranded mRNA", "text": text, **extra}


@pytest.fixture
def log(tmp_path):
    return str(tmp_path / "audit" / "payload_audit.jsonl")


def read_log(path):
    with open(path, encoding="utf8") as f:
        return [json.loads(line) for line in f]


# ---------- allowed payloads ----------

def test_extract_builds_and_logs(log):
    out = build_payload("extract", notes=NOTES, audit_log=log)
    assert out["payload"] == {"payload_version": 1, "task": "extract", "parts": {"notes": NOTES}}
    (record,) = read_log(log)
    assert record["status"] == "built" and record["sha256"] == out["sha256"] and record["payload"] == out["payload"]


def test_infer_with_chunks(log):
    out = build_payload("infer", notes=NOTES, fields={"kit_mentioned": "TruSeq Stranded mRNA"},
                        chunks=[chunk()], audit_log=log)
    assert set(out["payload"]["parts"]) == {"notes", "fields", "chunks"}


def test_explain_accepts_real_datacheck_and_reconcile_output(log):
    summary = data_summary()
    result = reconcile("RF", summary)
    out = build_payload("explain", data_summary=summary, reconcile=result,
                        inference={"kit": "TruSeq Stranded mRNA", "orientation": "RF"}, audit_log=log)
    assert out["payload"]["parts"]["reconcile"]["state"] == "CONCORDANT"


def test_allow_lists_match_the_modules_that_produce_them():
    assert set(data_summary()) == DATA_SUMMARY_KEYS
    for doc in ("RF", "FR", "INSUFFICIENT", "OUT_OF_SCOPE"):
        for data in ("RF", "UNSTRANDED", "INCONCLUSIVE", None):
            assert set(reconcile(doc, data)) == RECONCILE_KEYS


def test_primer_length_sequence_allowed(log):
    build_payload("extract", notes=f"Reverse primer {PRIMER} was used for RT.", audit_log=log)


def test_adapter_in_chunk_allowed(log):
    build_payload("infer", notes=NOTES, chunks=[chunk(f"Adapter read 1: {ADAPTER}")], audit_log=log)


def test_audit_log_is_append_only(log):
    build_payload("extract", notes=NOTES, audit_log=log)
    build_payload("extract", notes=NOTES + " Second run.", audit_log=log)
    assert len(read_log(log)) == 2


def test_input_not_modified_by_later_changes(log):
    fields = {"kit": "A"}
    out = build_payload("infer", notes=NOTES, fields=fields, audit_log=log)
    fields["kit"] = "B"
    assert out["payload"]["parts"]["fields"]["kit"] == "A"


# ---------- refused payloads ----------

def blocked(log, task, **parts):
    with pytest.raises(PayloadError) as err:
        build_payload(task, audit_log=log, **parts)
    record = read_log(log)[-1]
    assert record["status"] == "blocked" and "payload" not in record
    return str(err.value)


def test_unknown_task(log):
    assert "unknown task" in blocked(log, "summarise", notes=NOTES)


def test_part_not_allowed_for_task(log):
    assert "not allowed" in blocked(log, "extract", notes=NOTES, data_summary=data_summary())


def test_missing_required_part(log):
    assert "missing required parts" in blocked(log, "explain", data_summary=data_summary())


def test_unknown_data_summary_key(log):
    summary = {**data_summary(), "reads_1": "/home/user/data/sample_R1.fq.gz"}
    reason = blocked(log, "explain", data_summary=summary, reconcile=reconcile("RF", "RF"))
    assert "reads_1" in reason and "sample_R1" not in reason


def test_nested_data_summary_value(log):
    summary = {**data_summary(), "call": {"x": 1}}
    assert "must be a number" in blocked(log, "explain", data_summary=summary, reconcile=reconcile("RF", "RF"))


def test_unknown_reconcile_key(log):
    assert "allow-list" in blocked(log, "explain", reconcile={**reconcile("RF", "RF"), "extra": 1})


def test_chunk_missing_text(log):
    assert "missing required keys" in blocked(log, "infer", notes=NOTES, chunks=[{"chunk_id": "x"}])


def test_odd_key_name_not_echoed(log):
    reason = blocked(log, "infer", notes=NOTES, chunks=[{**chunk(), READ: 1}])
    assert READ not in reason and "<unprintable key>" in reason


@pytest.mark.parametrize("text,label", [
    (f"Read looked like {READ[:MIN_SEQUENCE_RUN]}", "nucleotide run"),
    (f"lower case too: {READ.lower()}", "nucleotide run"),
    (FASTQ_RECORD, "nucleotide run"),
    (f"key {API_KEY}", "API key"),
    ("x" * 50_001, "longer than"),
])
def test_notes_content_guards(log, text, label):
    reason = blocked(log, "extract", notes=text)
    assert label in reason


def test_fastq_record_blocked_even_in_chunks(log):
    assert "FASTQ record" in blocked(log, "infer", notes=NOTES, chunks=[chunk(FASTQ_RECORD)])


def test_read_hidden_in_nested_llm_output(log):
    assert "inference.evidence[1]" in blocked(log, "explain", reconcile=reconcile("RF", "RF"),
                                              inference={"evidence": ["ok", READ]})


def test_unsupported_type(log):
    assert "not JSON-serialisable" in blocked(log, "infer", notes=NOTES, fields={"raw": b"bytes"})


def test_empty_notes(log):
    assert "non-empty" in blocked(log, "extract", notes="   ")


# ---------- plan §12: no read sequences in the audit log ----------

def test_no_read_sequences_in_audit_log(log):
    # Try to smuggle a read (and a key) through every part; also log some valid payloads.
    build_payload("extract", notes=NOTES, audit_log=log)
    attempts = [
        ("extract", {"notes": f"{NOTES}\n{FASTQ_RECORD}"}),
        ("infer", {"notes": NOTES, "fields": {"seq": READ}}),
        ("infer", {"notes": NOTES, "chunks": [chunk(FASTQ_RECORD)]}),
        ("explain", {"reconcile": {**reconcile("RF", "RF"), "message": READ}}),
        ("explain", {"reconcile": reconcile("RF", "RF"), "data_summary": {**data_summary(), "reason": READ}}),
        ("explain", {"reconcile": reconcile("RF", "RF"), "inference": {"note": API_KEY}}),
    ]
    for task, parts in attempts:
        with pytest.raises(PayloadError):
            build_payload(task, audit_log=log, **parts)
    build_payload("explain", reconcile=reconcile("RF", data_summary()), data_summary=data_summary(), audit_log=log)

    with open(log, encoding="utf8") as f:
        text = f.read()
    assert READ not in text and READ[:MIN_SEQUENCE_RUN] not in text and API_KEY not in text
    assert check_audit_log(log) == []
    assert [r["status"] for r in read_log(log)] == ["built"] + ["blocked"] * len(attempts) + ["built"]


def test_check_audit_log_finds_tampered_line(log):
    build_payload("extract", notes=NOTES, audit_log=log)
    record = read_log(log)[0]
    record["payload"]["parts"]["notes"] = READ
    with open(log, "a", encoding="utf8") as f:
        f.write(json.dumps(record) + "\n")
    problems = check_audit_log(log)
    assert len(problems) == 1 and problems[0].startswith("line 2 notes")
