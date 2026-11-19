# File: tests/test_extract.py
# Version: 0.1.0
# Last modified: 2026-11-19 (XD)
# Change: Tests for step 1: quote checks, allowed values, scope, questions, prompt file, end-to-end with a fake API.
import json
import re

import pytest

from seqseec.extract import FIELDS, PROMPT_ID, extract, interpret, load_prompt
from seqseec.payload import PayloadError

NOTES = ("Total RNA from HeLa cells was poly(A)-selected and libraries were built with the "
         "NEBNext Ultra II Directional RNA Library Prep Kit, then sequenced 2x100 on a NovaSeq 6000.")


def answer(fields=None, evidence=None):
    return {"fields": {**dict.fromkeys(FIELDS), **(fields or {})}, "evidence": evidence or {}}


GOOD = answer(
    {"kit_name": "NEBNext Ultra II Directional RNA Library Prep Kit", "strand_statement": "Directional",
     "rna_selection": "polyA", "read_layout": "PE", "platform": "NovaSeq 6000", "organism": "HeLa cells"},
    {"kit_name": "NEBNext Ultra II Directional RNA Library Prep Kit", "strand_statement": "Directional",
     "rna_selection": "poly(A)-selected", "read_layout": "2x100", "platform": "NovaSeq 6000",
     "organism": "HeLa cells"})


# ---------- quote checks ----------

def test_good_answer_kept():
    out = interpret(NOTES, GOOD)
    assert out["fields"]["kit_name"] == "NEBNext Ultra II Directional RNA Library Prep Kit"
    assert out["fields"]["read_layout"] == "PE" and out["rejected"] == []
    assert out["scope"] == "IN_SCOPE" and set(out["fields"]) == set(FIELDS)


def test_field_without_quote_dropped():
    out = interpret(NOTES, answer({"vendor": "NEB"}))
    assert out["fields"]["vendor"] is None
    assert out["rejected"] == [{"field": "vendor", "reason": "no supporting quote"}]


def test_invented_quote_dropped():
    out = interpret(NOTES, answer({"chemistry": "dUTP"}, {"chemistry": "dUTP second-strand marking"}))
    assert out["fields"]["chemistry"] is None
    assert out["rejected"][0]["reason"] == "quote not found in the notes"


def test_quote_match_ignores_case_spacing_and_curly_quotes():
    notes = "Kit:  “TruSeq   Stranded mRNA” (Illumina)."
    out = interpret(notes, answer({"kit_name": "TruSeq Stranded mRNA"}, {"kit_name": '"truseq stranded\nmrna"'}))
    assert out["fields"]["kit_name"] == "TruSeq Stranded mRNA"


def test_unknown_field_reported():
    out = interpret(NOTES, {"fields": {"index_sequence": "ACGT"}, "evidence": {}})
    assert {"field": "index_sequence", "reason": "not a known field"} in out["rejected"]


@pytest.mark.parametrize("bad", [None, [], {"evidence": {}}, {"fields": "x"}])
def test_malformed_answer_raises(bad):
    with pytest.raises(ValueError):
        interpret(NOTES, bad)


# ---------- allowed values ----------

@pytest.mark.parametrize("field,value,expected", [
    ("read_layout", "paired-end", "PE"), ("read_layout", "single", "SE"),
    ("rna_selection", "poly-A", "polyA"), ("rna_selection", "ribo-depletion", "rRNA depletion"),
    ("library_type", "Single cell", "single-cell"), ("library_type", "bulk", "bulk"),
])
def test_allowed_values_normalized(field, value, expected):
    notes = "quoted text here"
    out = interpret(notes, answer({field: value}, {field: "quoted text"}))
    assert out["fields"][field] == expected


@pytest.mark.parametrize("field,value", [("read_layout", "2x100"), ("rna_selection", "magic"),
                                         ("library_type", "spatial"), ("kit_name", True), ("kit_name", ["x"]),
                                         ("organism", "x" * 201)])
def test_invalid_values_rejected(field, value):
    out = interpret("quoted text", answer({field: value}, {field: "quoted text"}))
    assert out["fields"][field] is None and out["rejected"][0]["field"] == field


def test_numeric_version_accepted():
    out = interpret("TruSeq RNA v2", answer({"kit_version": 2}, {"kit_version": "v2"}))
    assert out["fields"]["kit_version"] == "2"


# ---------- scope ----------

@pytest.mark.parametrize("fields,evidence_text", [
    ({"platform": "Oxford Nanopore MinION"}, "Oxford Nanopore MinION"),
    ({"platform": "PacBio Revio"}, "PacBio Revio"),
    ({"library_type": "single-cell"}, "single-cell"),
    ({"kit_name": "Chromium Single Cell 3' v3"}, "Chromium Single Cell 3' v3"),
])
def test_out_of_scope(fields, evidence_text):
    notes = f"Libraries: {evidence_text}."
    out = interpret(notes, answer(fields, {k: evidence_text for k in fields}))
    assert out["scope"] == "OUT_OF_SCOPE" and out["scope_reason"]
    assert out["questions"] == []


def test_unverified_platform_does_not_decide_scope():
    # A platform the notes do not support is dropped, so it cannot push a case out of scope.
    out = interpret(NOTES, answer({"platform": "Nanopore"}, {"platform": "Nanopore"}))
    assert out["scope"] == "IN_SCOPE"


def test_organism_warning():
    notes = "Zebrafish embryos, TruSeq Stranded mRNA."
    out = interpret(notes, answer({"organism": "Zebrafish"}, {"organism": "Zebrafish"}))
    assert out["warnings"] and "outside the tested scope" in out["warnings"][0]
    assert interpret(NOTES, answer({"organism": "human"}, {"organism": "HeLa"}))["warnings"] == []


# ---------- questions ----------

def test_questions_when_nothing_known():
    out = interpret(NOTES, answer())
    assert len(out["questions"]) == 2
    assert "library-prep kit" in out["questions"][0] and "paired-end" in out["questions"][1]


def test_question_for_missing_version():
    out = interpret(NOTES, GOOD)
    assert out["questions"] == ["Which version of NEBNext Ultra II Directional RNA Library Prep Kit was used? "
                                "Some kits changed read orientation between versions."]


def test_no_kit_question_when_strand_stated():
    notes = "Reverse-stranded libraries, 2x150."
    out = interpret(notes, answer({"strand_statement": "Reverse-stranded", "read_layout": "PE"},
                                  {"strand_statement": "Reverse-stranded", "read_layout": "2x150"}))
    assert out["questions"] == []


# ---------- prompt file ----------

def test_prompt_loads_without_header():
    text = load_prompt()
    assert not text.startswith("<!--") and "File: prompts" not in text
    assert "json" in text.lower()
    for field in FIELDS:
        assert f"`{field}`" in text


def test_prompt_example_passes_the_code_checks():
    # The example answer in the prompt must survive interpret() on the matching note.
    example = json.loads(re.search(r"Output format \(JSON\):\s*(\{.*\})\s*\Z", load_prompt(), re.DOTALL).group(1))
    out = interpret(NOTES, example)
    assert out["rejected"] == [] and out["fields"]["read_layout"] == "PE"


# ---------- end to end with a fake API ----------

class FakeTransport:
    def __init__(self, content):
        self.content, self.requests = content, []

    def __call__(self, url, headers, body, timeout):
        self.requests.append(body)
        return {"id": "r1", "model": "DeepSeek-V4.1-Flash-1017",
                "choices": [{"finish_reason": "stop", "message": {"content": self.content}}],
                "usage": {"total_tokens": 1}}


@pytest.fixture
def run(tmp_path):
    logs = {"audit_log": str(tmp_path / "a.jsonl"), "call_log": str(tmp_path / "c.jsonl")}
    config = {"api_key": "sk-test", "model": "deepseek-flash", "base_url": "https://api.example.test"}

    def _run(notes, content):
        fake = FakeTransport(content)
        return extract(notes, config=config, transport=fake, **logs), fake
    return _run


def test_extract_end_to_end(run):
    out, fake = run(NOTES, json.dumps(GOOD))
    assert out["fields"]["kit_name"].startswith("NEBNext") and out["scope"] == "IN_SCOPE"
    assert out["llm"]["prompt_id"] == PROMPT_ID and out["llm"]["response_model"] == "DeepSeek-V4.1-Flash-1017"
    system, user = fake.requests[0]["messages"]
    assert system["content"] == load_prompt()
    assert json.loads(user["content"])["parts"] == {"notes": NOTES}


def test_extract_refuses_notes_with_reads(run):
    with pytest.raises(PayloadError):
        run(NOTES + " ACGTACGTACGTACGTACGTACGTACGTACGTACGT", json.dumps(GOOD))


def test_extract_bad_shape_raises(run):
    with pytest.raises(ValueError):
        run(NOTES, json.dumps({"kit": "x"}))
