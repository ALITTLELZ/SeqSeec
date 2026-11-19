# File: tests/test_llm.py
# Version: 0.1.0
# Last modified: 2026-11-19 (XD)
# Change: Tests for the LLM client with a fake transport (no network, no API key needed).
import json

import pytest

from seqseec.llm import DEFAULT_BASE_URL, DEFAULT_MODEL, LLMError, call_llm, get_config, read_env_file
from seqseec.payload import build_payload

KEY = "sk-test" + "0123456789abcdef"
CONFIG = {"api_key": KEY, "model": "deepseek-flash", "base_url": "https://api.example.test"}
PROMPT = "Extract the library-prep kit from the notes. Answer in JSON: {\"kit\": string or null}."
NOTES = "Libraries were prepared with the TruSeq Stranded mRNA kit."


def response(content='{"kit": "TruSeq Stranded mRNA"}', finish="stop"):
    return {"id": "resp-1", "model": "DeepSeek-V4.1-Flash-1017", "system_fingerprint": "fp_1",
            "choices": [{"index": 0, "finish_reason": finish, "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60}}


class FakeTransport:
    """Returns (or raises) the given items in order and records each request."""

    def __init__(self, *items):
        self.items, self.requests = list(items), []

    def __call__(self, url, headers, body, timeout):
        self.requests.append({"url": url, "headers": headers, "body": body})
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def paths(tmp_path):
    return {"audit": str(tmp_path / "audit" / "payload_audit.jsonl"),
            "calls": str(tmp_path / "audit" / "llm_calls.jsonl")}


@pytest.fixture
def built(paths):
    return build_payload("extract", notes=NOTES, audit_log=paths["audit"])


def call(built, paths, transport, **kw):
    return call_llm(built, PROMPT, "extract_v1", config=CONFIG, transport=transport, call_log=paths["calls"], **kw)


def log_lines(path):
    with open(path, encoding="utf8") as f:
        return [json.loads(line) for line in f]


# ---------- normal call ----------

def test_successful_call(built, paths):
    fake = FakeTransport(response())
    out = call(built, paths, fake)
    assert out["output"] == {"kit": "TruSeq Stranded mRNA"}
    rec = out["record"]
    assert rec["status"] == "ok" and rec["attempt"] == 1
    assert rec["requested_model"] == "deepseek-flash" and rec["response_model"] == "DeepSeek-V4.1-Flash-1017"
    assert rec["payload_sha256"] == built["sha256"] and rec["prompt_id"] == "extract_v1"
    assert rec["usage"]["total_tokens"] == 60
    (logged,) = log_lines(paths["calls"])
    logged.pop("logged_at")
    assert logged == rec


def test_request_contents(built, paths):
    fake = FakeTransport(response())
    call(built, paths, fake)
    req = fake.requests[0]
    assert req["url"] == "https://api.example.test/chat/completions"
    assert req["headers"]["Authorization"] == f"Bearer {KEY}"
    body = req["body"]
    assert body["model"] == "deepseek-flash" and body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0.0 and body["stream"] is False
    system, user = body["messages"]
    assert system == {"role": "system", "content": PROMPT}
    assert user["role"] == "user" and json.loads(user["content"]) == built["payload"]


def test_api_key_never_logged(built, paths):
    with pytest.raises(LLMError):
        call(built, paths, FakeTransport(LLMError("HTTP 401 from the LLM API: invalid key")))
    call(built, paths, FakeTransport(response()))
    with open(paths["calls"], encoding="utf8") as f:
        assert KEY not in f.read()


# ---------- refused before any request ----------

@pytest.mark.parametrize("bad", [
    {"payload": {"task": "extract"}},                       # no hash
    {"task": "extract", "parts": {"notes": NOTES}},          # raw dict, not built
    "just text",
])
def test_rejects_input_not_from_build_payload(paths, bad):
    fake = FakeTransport()
    with pytest.raises(LLMError, match="build_payload"):
        call(bad, paths, fake)
    assert fake.requests == []


def test_rejects_payload_changed_after_build(built, paths):
    built["payload"]["parts"]["notes"] = "something else"
    fake = FakeTransport()
    with pytest.raises(LLMError, match="changed after"):
        call(built, paths, fake)
    assert fake.requests == []


def test_prompt_must_mention_json(built, paths):
    fake = FakeTransport()
    with pytest.raises(LLMError, match="JSON"):
        call_llm(built, "Extract the kit.", "extract_v1", config=CONFIG, transport=fake, call_log=paths["calls"])
    assert fake.requests == []


def test_prompt_id_required(built, paths):
    with pytest.raises(LLMError, match="prompt_id"):
        call_llm(built, PROMPT, "", config=CONFIG, transport=FakeTransport(), call_log=paths["calls"])


def test_missing_api_key(built, paths):
    fake = FakeTransport()
    with pytest.raises(LLMError, match="DEEPSEEK_API_KEY"):
        call_llm(built, PROMPT, "extract_v1", config={**CONFIG, "api_key": None}, transport=fake,
                 call_log=paths["calls"])
    assert fake.requests == []


# ---------- retries ----------

@pytest.mark.parametrize("first", [response(content="   "), response(content="{not json"),
                                   response(content="[1, 2]"), LLMError("HTTP 503", retryable=True)])
def test_retry_then_success(built, paths, first):
    fake = FakeTransport(first, response())
    out = call(built, paths, fake)
    assert out["record"]["attempt"] == 2 and len(fake.requests) == 2
    assert [r["status"] for r in log_lines(paths["calls"])] == ["error", "ok"]


def test_gives_up_after_max_attempts(built, paths):
    fake = FakeTransport(response(content=""), response(content=""))
    with pytest.raises(LLMError, match="empty content"):
        call(built, paths, fake)
    assert [r["status"] for r in log_lines(paths["calls"])] == ["error", "error"]


@pytest.mark.parametrize("first", [response(finish="length"), {"unexpected": True},
                                   LLMError("HTTP 401 from the LLM API", retryable=False)])
def test_no_retry_for_permanent_errors(built, paths, first):
    fake = FakeTransport(first, response())
    with pytest.raises(LLMError):
        call(built, paths, fake)
    assert len(fake.requests) == 1


# ---------- configuration ----------

def test_env_file_parsing(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comment\n\nDEEPSEEK_API_KEY='abc'\nexport SEQSEEC_LLM_MODEL=\"deepseek-v4-pro\"\nJUNK\n")
    assert read_env_file(str(env)) == {"DEEPSEEK_API_KEY": "abc", "SEQSEEC_LLM_MODEL": "deepseek-v4-pro"}
    assert read_env_file(str(tmp_path / "missing.env")) == {}


def test_config_defaults_and_precedence(tmp_path, monkeypatch):
    for name in ("DEEPSEEK_API_KEY", "SEQSEEC_LLM_MODEL", "SEQSEEC_LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    env.write_text("DEEPSEEK_API_KEY=from-file\nSEQSEEC_LLM_MODEL=deepseek-v4-pro\n")
    assert get_config(str(tmp_path / "none.env")) == {"api_key": None, "model": DEFAULT_MODEL,
                                                      "base_url": DEFAULT_BASE_URL}
    assert get_config(str(env))["api_key"] == "from-file"
    monkeypatch.setenv("SEQSEEC_LLM_MODEL", "deepseek-flash")
    monkeypatch.setenv("SEQSEEC_LLM_BASE_URL", "https://proxy.test/")
    cfg = get_config(str(env))
    assert cfg["model"] == "deepseek-flash" and cfg["base_url"] == "https://proxy.test"
