# File: tests/test_infer.py
# Version: 0.1.0
# Last modified: 2026-11-19 (Track B)
# Change: Tests for step 3: rules-only inference, LLM answer checks (citations, look-alikes), and the baseline.
import pytest

from seqseec.infer import infer, infer_rules, infer_without_retrieval, interpret
from seqseec.retrieve import load_registry, retrieve

REG = load_registry()
NEB_NOTES = ("Total RNA was poly(A)-selected and libraries were built with the NEBNext Ultra II Directional "
             "RNA Library Prep Kit, then sequenced 2x100 on a NovaSeq 6000.")
NEB_QUOTE = "high quality directional (strand-specific) libraries"
CONFIG = {"mode": "api", "api_key": "sk-test", "model": "deepseek-flash", "base_url": "https://api.example.test"}


# ---------- rules only ----------

@pytest.mark.parametrize("notes,orientation", [
    (NEB_NOTES, "RF"),
    ("NEBNext Ultra II RNA Library Prep Kit (non-directional)", "UNSTRANDED"),
    ("TruSeq RNA Library Prep Kit v2", "UNSTRANDED"),
    ("CORALL Total RNA-Seq", "FR"),
    ("dUTP second-strand marking", "RF"),
    ("NEBNext Ultra II kit", "AMBIGUOUS"),
    ("TruSeq Stranded kit", "RF"),            # family name, but both members are RF
    ("KAPA HyperPrep stranded mRNA kit", "INSUFFICIENT"),   # keyword only: rules do not guess
    ("sequenced on a NovaSeq", "INSUFFICIENT"),
])
def test_rules(notes, orientation):
    assert infer_rules(notes)["document_orientation"] == orientation


def test_rules_report_kit_and_source():
    out = infer_rules(NEB_NOTES)
    assert out["kit_id"] == "nebnext_ultra2_directional" and out["evidence_type"] == "inferred_from_chemistry"
    assert out["source_url"].startswith("https://www.neb.com/")


# ---------- LLM answer checks ----------

def answer(**over):
    base = {"decision": "KIT", "kit_id": "nebnext_ultra2_directional",
            "notes_quote": "NEBNext Ultra II Directional RNA Library Prep Kit",
            "citation": {"chunk_id": "nebnext_ultra2_directional", "quote": NEB_QUOTE}, "reason": "named"}
    base.update(over)
    return base


def check(notes, output):
    return interpret(notes, output, retrieve(notes, registry=REG), REG)


def test_good_answer_takes_orientation_from_registry():
    out = check(NEB_NOTES, answer())
    assert out["document_orientation"] == "RF" and out["citation"]["quote"] == NEB_QUOTE and not out["rejected"]


@pytest.mark.parametrize("over,why", [
    ({"kit_id": "truseq_stranded_mrna"}, "not one of the retrieved candidates"),
    ({"notes_quote": "Ultra II Directional kit from NEB"}, "notes_quote not found"),
    ({"notes_quote": None}, "no quote from the notes"),
    ({"citation": {"chunk_id": "nebnext_ultra2_directional", "quote": "read 1 is always antisense to RNA"}},
     "citation quote not found"),
    ({"citation": {"chunk_id": "chem_dutp", "quote": NEB_QUOTE}}, "citation must come from the chosen entry"),
    ({"citation": {"chunk_id": "nebnext_ultra2_directional", "quote": "dUTP"}}, "too short"),
    ({"decision": "MAYBE"}, "known decision"),
])
def test_bad_answers_are_rejected(over, why):
    out = check(NEB_NOTES, answer(**over))
    assert out["document_orientation"] == "INSUFFICIENT" and why in out["rejected"][0]


def test_llm_cannot_pick_a_look_alike_from_a_family_name():
    notes = "Libraries were made with the NEBNext Ultra II kit."
    out = check(notes, answer(notes_quote="NEBNext Ultra II"))
    assert out["document_orientation"] == "AMBIGUOUS"


def test_ambiguous_with_agreeing_candidates_still_gives_orientation():
    out = check("TruSeq Stranded kit", {"decision": "AMBIGUOUS", "reason": "mRNA or Total"})
    assert out["document_orientation"] == "RF" and out["kit_id"] is None


def test_keyword_candidate_can_be_chosen_with_a_quote():
    notes = "KAPA HyperPrep stranded mRNA kit (Roche)"
    out = check(notes, {"decision": "KIT", "kit_id": "kapa_mrna_hyperprep", "notes_quote": "KAPA HyperPrep stranded mRNA kit",
                        "citation": {"chunk_id": "kapa_mrna_hyperprep",
                                     "quote": "The strand marked with dUTP is not amplified"}, "reason": "named"})
    assert out["document_orientation"] == "RF" and out["retrieval_method"] == "keyword"


# ---------- full calls with a fake transport ----------

def fake_transport(output):
    import json
    calls = []

    def _post(url, headers, body, timeout):
        calls.append(body)
        return {"model": "deepseek-flash", "choices": [{"message": {"content": json.dumps(output)},
                                                         "finish_reason": "stop"}],
                "usage": {"total_tokens": 10}}
    return _post, calls


def test_infer_sends_chunks_and_checks_answer(tmp_path):
    post, calls = fake_transport(answer())
    out = infer(NEB_NOTES, {"kit_name": "NEBNext Ultra II Directional RNA Library Prep Kit"}, config=CONFIG,
                transport=post, audit_log=str(tmp_path / "a.jsonl"), call_log=str(tmp_path / "c.jsonl"))
    assert out["document_orientation"] == "RF" and out["rules_orientation"] == "RF"
    assert len(calls) == 1 and "nebnext_ultra2_directional" in calls[0]["messages"][1]["content"]


def test_infer_without_candidates_makes_no_call(tmp_path):
    post, calls = fake_transport(answer())
    out = infer("sequenced on a NovaSeq", config=CONFIG, transport=post,
                audit_log=str(tmp_path / "a.jsonl"), call_log=str(tmp_path / "c.jsonl"))
    assert out["document_orientation"] == "INSUFFICIENT" and calls == [] and out["llm"] is None


def test_baseline_has_no_chunks(tmp_path):
    post, calls = fake_transport({"orientation": "rf", "kit": "NEBNext", "reason": "dUTP"})
    out = infer_without_retrieval(NEB_NOTES, config=CONFIG, transport=post,
                                  audit_log=str(tmp_path / "a.jsonl"), call_log=str(tmp_path / "c.jsonl"))
    assert out["document_orientation"] == "RF" and "chunks" not in calls[0]["messages"][1]["content"]
