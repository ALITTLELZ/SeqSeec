# File: tests/test_cli.py
# Version: 0.2.0
# Last modified: 2026-11-19 (Track B)
# Change: Fake server also answers step 3 (infer); local-mode test now covers both LLM calls.
import functools
import json
import os
import pathlib
import subprocess
import sys

import pytest

from seqseec.cli import main
from seqseec.extract import extract
from seqseec.infer import infer
from seqseec.llm import LLMError

ROOT = pathlib.Path(__file__).resolve().parents[1]
NOTES = ("Libraries were built with the NEBNext Ultra II Directional RNA Library Prep Kit "
         "and sequenced 2x100 on a NovaSeq 6000.")
ANSWER = {"fields": {"kit_name": "NEBNext Ultra II Directional RNA Library Prep Kit", "read_layout": "PE"},
          "evidence": {"kit_name": "NEBNext Ultra II Directional RNA Library Prep Kit", "read_layout": "2x100"}}
INFER_ANSWER = {"decision": "KIT", "kit_id": "nebnext_ultra2_directional",
                "notes_quote": "NEBNext Ultra II Directional RNA Library Prep Kit",
                "citation": {"chunk_id": "nebnext_ultra2_directional",
                             "quote": "high quality directional (strand-specific) libraries"}, "reason": "named"}


class FakeServer:
    """Stands in for the LLM server; records every request."""

    def __init__(self, error=None):
        self.error, self.requests = error, []

    def __call__(self, url, headers, body, timeout):
        self.requests.append({"url": url, "headers": headers, "timeout": timeout})
        if self.error:
            raise self.error
        is_infer = "kit registry" in body["messages"][0]["content"]
        return {"id": "r", "model": "served-model",
                "choices": [{"finish_reason": "stop",
                             "message": {"content": json.dumps(INFER_ANSWER if is_infer else ANSWER)}}]}


@pytest.fixture
def work(tmp_path, monkeypatch):
    """Run in an empty folder with no LLM settings in the environment."""
    monkeypatch.chdir(tmp_path)
    for name in ("DEEPSEEK_API_KEY", "SEQSEEC_LLM_MODEL", "SEQSEEC_LLM_BASE_URL",
                 "SEQSEEC_LOCAL_MODEL", "SEQSEEC_LOCAL_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "notes.txt").write_text(NOTES, encoding="utf8")
    return tmp_path


def stages(server):
    return {"extract": functools.partial(extract, transport=server),
            "infer": functools.partial(infer, transport=server)}


# ---------- run ----------

def test_no_llm_run(work, capsys):
    assert main(["run", "--llm", "none", "--expected", "rf", "--data-call", "RF"]) == 0
    out = capsys.readouterr().out
    assert "RESULT: CONCORDANT" in out and "-s 2" in out and "ISR" in out


def test_json_format_and_out_file(work, capsys):
    code = main(["run", "--llm", "none", "--expected", "FR", "--data-call", "RF", "--format", "json",
                 "--out", "reports/r.json"])
    printed = json.loads(capsys.readouterr().out)
    saved = json.loads((work / "reports" / "r.json").read_text(encoding="utf8"))
    assert code == 0 and printed == saved and saved["result"]["state"] == "CONFLICT"


def test_api_mode_without_key_stops_before_any_step(work, capsys):
    server = FakeServer()
    assert main(["run", "--notes", "notes.txt", "--data-call", "RF"], stages=stages(server)) == 2
    err = capsys.readouterr().err
    assert "DEEPSEEK_API_KEY" in err and "--llm local" in err and server.requests == []


def test_api_mode_with_key_from_env_file(work, capsys):
    (work / ".env").write_text("DEEPSEEK_API_KEY=sk-test-from-file\n")
    server = FakeServer()
    assert main(["run", "--notes", "notes.txt", "--data-call", "RF", "--expected", "RF"],
                stages=stages(server)) == 0
    req = server.requests[0]
    assert req["url"] == "https://api.deepseek.com/chat/completions"
    assert req["headers"]["Authorization"] == "Bearer sk-test-from-file"
    out = capsys.readouterr().out
    assert "LLM: api (deepseek-flash)" in out and "RESULT: CONCORDANT" in out


def test_local_mode_needs_no_key_and_never_sends_one(work, capsys, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-hosted-key-must-not-leak")
    server = FakeServer()
    code = main(["run", "--notes", "notes.txt", "--llm", "local", "--model", "llama3.1:8b",
                 "--data-call", "RF"], stages=stages(server))
    assert code == 0 and len(server.requests) == 2          # step 1 extract + step 3 infer
    for req in server.requests:
        assert req["url"] == "http://localhost:11434/v1/chat/completions"
        assert "Authorization" not in req["headers"] and req["timeout"] == 300
    out = capsys.readouterr().out
    assert "LLM: local (llama3.1:8b)" in out and "RESULT: CONCORDANT" in out
    log = (work / "audit" / "llm_calls.jsonl").read_text(encoding="utf8")
    assert '"mode": "local"' in log and "sk-hosted" not in log


def test_local_mode_refuses_remote_url(work, capsys):
    server = FakeServer()
    assert main(["run", "--notes", "notes.txt", "--llm", "local", "--base-url", "https://api.deepseek.com"],
                stages=stages(server)) == 2
    assert "not localhost" in capsys.readouterr().err and server.requests == []


def test_local_server_down_gives_hint_and_exit_1(work, capsys):
    server = FakeServer(LLMError("could not reach the LLM API: connection refused", retryable=True))
    assert main(["run", "--notes", "notes.txt", "--llm", "local", "--data-call", "RF"],
                stages=stages(server)) == 1
    out = capsys.readouterr().out
    assert "ollama serve" in out and "RESULT: DATA_ONLY" in out


def test_notes_from_stdin(work, capsys, monkeypatch):
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO(NOTES))
    server = FakeServer()
    assert main(["run", "--notes", "-", "--llm", "local", "--expected", "RF"], stages=stages(server)) == 0
    assert "NEBNext" in capsys.readouterr().out


def test_reads_reach_the_data_check(work, capsys):
    for name in ("R1.fq.gz", "R2.fq.gz", "g.gtf", "t.fa"):
        (work / name).write_text("")
    seen = []

    def datacheck(gtf, transcripts, r1, r2, **kw):
        seen.append((gtf, transcripts, r1, r2, kw))
        return {"layout": "PE", "call": "RF"}
    code = main(["run", "--llm", "none", "--expected", "RF", "--r1", "R1.fq.gz", "--r2", "R2.fq.gz",
                 "--gtf", "g.gtf", "--transcripts", "t.fa", "--nreads", "1000", "--index-name", "toy"],
                stages={"datacheck": datacheck})
    assert code == 0 and seen[0][:4] == ("g.gtf", "t.fa", "R1.fq.gz", "R2.fq.gz")
    assert seen[0][4] == {"index_name": "toy", "env": "seqseec-tools", "nreads": 1000}


# ---------- argument checks (exit 2) ----------

@pytest.mark.parametrize("argv", [
    ["run"],                                                       # nothing to work on
    ["run", "--llm", "none", "--r1", "R1.fq.gz"],                  # no gtf / transcripts
    ["run", "--llm", "none", "--r2", "R2.fq.gz", "--expected", "RF"],
    ["run", "--llm", "none", "--expected", "sideways"],
    ["run", "--llm", "cloud", "--expected", "RF"],
    ["run", "--llm", "none", "--data-call", "maybe"],
    ["run", "--notes", "missing.txt", "--llm", "none"],
    ["run", "--llm", "none", "--r1", "x.fq", "--gtf", "g", "--transcripts", "t"],   # files do not exist
    ["frobnicate"],
])
def test_bad_arguments_exit_2(work, argv):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2


# ---------- settings ----------

def test_settings_command(capsys):
    assert main(["settings", "fr-firststrand", "--layout", "SE"]) == 0
    out = capsys.readouterr().out
    assert "RF (fr-firststrand), SE" in out and "-l SR" in out and "--rna-strandness RF" not in out


def test_python_dash_m(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    proc = subprocess.run([sys.executable, "-m", "seqseec", "settings", "UNSTRANDED"],
                          capture_output=True, text=True, cwd=tmp_path, env=env)
    assert proc.returncode == 0 and "fr-unstranded" in proc.stdout
