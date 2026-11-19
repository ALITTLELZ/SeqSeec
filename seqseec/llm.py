# File: seqseec/llm.py
# Version: 0.2.0
# Last modified: 2026-11-19 (XD)
# Change: Add local mode (OpenAI-compatible server on this machine, e.g. Ollama): no API key, loopback host only.
"""The only module that talks to the LLM (plan §2: "a thin LLM interface so the
model can be swapped later in one place").

call_llm() sends exactly one payload made by seqseec.payload.build_payload():
  * it refuses anything else, and refuses a payload changed after it was built
    (its SHA-256 must still match), so nothing can bypass the payload checks;
  * it uses JSON mode (response_format json_object) and returns a parsed JSON
    object; the system prompt must mention JSON, as the API requires;
  * it retries once on the known JSON-mode failure (blank or invalid content)
    and on HTTP 429/5xx; it does not retry an answer cut off at max_tokens;
  * it appends one record per attempt to audit/llm_calls.jsonl: task, prompt ID
    and hash, payload hash, requested and returned model IDs, token usage,
    time, and the parsed output. The API key is never logged.

Two modes (both speak the OpenAI-style /chat/completions API, so the code path is the same):
  api    DeepSeek's hosted API. The notes leave the machine; needs an API key.
  local  a model server on this machine, e.g. Ollama. Nothing leaves the machine:
         the base URL must point to localhost (127.0.0.1 / ::1), and no API key is sent.

Configuration (environment variables, or a git-ignored .env file in the working directory):
  api mode:
    DEEPSEEK_API_KEY        required to make calls
    SEQSEEC_LLM_MODEL       default "deepseek-flash" (served by DeepSeek-V4.1-Flash-1017 as of 2026-11-19)
    SEQSEEC_LLM_BASE_URL    default "https://api.deepseek.com"
  local mode:
    SEQSEEC_LOCAL_MODEL     default "qwen3.5:2b" (any model pulled into the local server)
    SEQSEEC_LOCAL_BASE_URL  default "http://localhost:11434/v1" (Ollama's OpenAI-compatible endpoint)
    Local requests also send reasoning_effort "none": "thinking" models such as Qwen3
    otherwise spend the whole token budget reasoning and return blank JSON. On
    2026-11-19, qwen3.5:2b on Ollama 0.40.16 took 4 min and hit max_tokens without it,
    and answered in about 5 s with it.
"""
import datetime
import hashlib
import ipaddress
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

MODES = ("api", "local")

ENV_KEY = "DEEPSEEK_API_KEY"
ENV_MODEL = "SEQSEEC_LLM_MODEL"
ENV_BASE_URL = "SEQSEEC_LLM_BASE_URL"
DEFAULT_MODEL = "deepseek-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"

ENV_LOCAL_MODEL = "SEQSEEC_LOCAL_MODEL"
ENV_LOCAL_BASE_URL = "SEQSEEC_LOCAL_BASE_URL"
DEFAULT_LOCAL_MODEL = "qwen3.5:2b"
# Extra request fields for local mode; added only if the body does not already have the key.
LOCAL_EXTRA_BODY = {"reasoning_effort": "none"}
DEFAULT_LOCAL_BASE_URL = "http://localhost:11434/v1"

# Local models can take minutes to load on first use.
DEFAULT_TIMEOUT = {"api": 60, "local": 300}
DEFAULT_CALL_LOG = os.path.join("audit", "llm_calls.jsonl")
DEFAULT_MAX_TOKENS = 2000
DEFAULT_MAX_ATTEMPTS = 2
RETRYABLE_HTTP = {429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    """An LLM call failed. retryable tells call_llm whether another attempt may help."""

    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


# ---------- configuration ----------

def read_env_file(path=".env"):
    """Parse KEY=VALUE lines (comments, blank lines and surrounding quotes allowed). Missing file -> {}."""
    values = {}
    if not os.path.exists(path):
        return values
    with open(path, encoding="utf8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key.startswith("export "):
                key = key[len("export "):].strip()
            values[key] = value.strip().strip("'\"")
    return values


def get_config(env_file=".env", mode="api"):
    """Return {"mode", "api_key", "model", "base_url", "timeout"} for mode "api" or "local".

    Environment variables win over .env; defaults fill the rest. Local mode never
    reads DEEPSEEK_API_KEY, so the hosted key cannot be sent to another server.
    """
    if mode not in MODES:
        raise ValueError(f"LLM mode must be one of {MODES}, not {mode!r}")
    from_file = read_env_file(env_file)

    def get(name, default=None):
        return os.environ.get(name) or from_file.get(name) or default

    if mode == "local":
        return {"mode": "local", "api_key": None, "model": get(ENV_LOCAL_MODEL, DEFAULT_LOCAL_MODEL),
                "base_url": get(ENV_LOCAL_BASE_URL, DEFAULT_LOCAL_BASE_URL).rstrip("/"),
                "timeout": DEFAULT_TIMEOUT["local"], "extra_body": dict(LOCAL_EXTRA_BODY)}
    return {"mode": "api", "api_key": get(ENV_KEY), "model": get(ENV_MODEL, DEFAULT_MODEL),
            "base_url": get(ENV_BASE_URL, DEFAULT_BASE_URL).rstrip("/"), "timeout": DEFAULT_TIMEOUT["api"]}


def is_loopback_url(url):
    """True if url points to this machine (localhost, 127.0.0.0/8 or ::1)."""
    host = urllib.parse.urlsplit(url).hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_config(config):
    """Raise LLMError if config cannot make a call; no request is sent. Returns the mode."""
    mode = config.get("mode", "api")
    if mode not in MODES:
        raise LLMError(f"LLM mode must be one of {MODES}, not {mode!r}")
    if mode == "api" and not config.get("api_key"):
        raise LLMError(f"no API key: set {ENV_KEY} in the environment or in .env")
    if mode == "local" and not is_loopback_url(config.get("base_url", "")):
        raise LLMError(f"local mode only talks to a server on this machine; {config.get('base_url')!r} "
                       f"is not localhost. Use api mode for a remote server.")
    return mode


# ---------- transport ----------

def http_post(url, headers, body, timeout):
    """POST JSON and return the decoded JSON response. Tests replace this with a fake."""
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf8"))
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf8", "replace")[:300]
        raise LLMError(f"HTTP {err.code} from the LLM API: {detail}", retryable=err.code in RETRYABLE_HTTP) from None
    except (urllib.error.URLError, TimeoutError) as err:
        raise LLMError(f"could not reach the LLM API: {getattr(err, 'reason', err)}", retryable=True) from None
    except ValueError:
        raise LLMError("LLM API returned a response that is not JSON", retryable=True) from None


# ---------- helpers ----------

def _sha256(text):
    return hashlib.sha256(text.encode("utf8")).hexdigest()


def _canonical(payload):
    # Must match seqseec.payload's canonical form; tests check that build_payload() output verifies.
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _verify_built(built):
    if not isinstance(built, dict) or set(built) != {"payload", "sha256"} or not isinstance(built["payload"], dict):
        raise LLMError("input must be the return value of seqseec.payload.build_payload()")
    if _sha256(_canonical(built["payload"])) != built["sha256"]:
        raise LLMError("payload was changed after build_payload(); build it again")


def _parse(response):
    """Return (output dict, response metadata) or raise LLMError."""
    try:
        choice = response["choices"][0]
        content = choice["message"]["content"]
        finish = choice.get("finish_reason")
    except (KeyError, IndexError, TypeError):
        raise LLMError("unexpected response format from the LLM API") from None
    if finish == "length":
        raise LLMError("output was cut off at max_tokens; raise max_tokens")
    if not content or not content.strip():
        raise LLMError("empty content (JSON mode blanks invalid JSON)", retryable=True)
    try:
        output = json.loads(content)
    except ValueError:
        raise LLMError("output is not valid JSON", retryable=True) from None
    if not isinstance(output, dict):
        raise LLMError("output must be a JSON object", retryable=True)
    info = {"response_model": response.get("model"), "response_id": response.get("id"),
            "system_fingerprint": response.get("system_fingerprint"), "finish_reason": finish,
            "usage": response.get("usage")}
    return output, info


def _log(path, record):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    record = {"logged_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), **record}
    with open(path, "a", encoding="utf8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


# ---------- public API ----------

def call_llm(built, system_prompt, prompt_id, *, config=None, transport=http_post, call_log=DEFAULT_CALL_LOG,
             temperature=0.0, max_tokens=DEFAULT_MAX_TOKENS, max_attempts=DEFAULT_MAX_ATTEMPTS, timeout=None):
    """Send one built payload to the LLM and return {"output": dict, "record": dict}.

    built:         return value of seqseec.payload.build_payload()
    system_prompt: prompt text; must mention JSON
    prompt_id:     version label of the prompt, e.g. "infer_v2" (plan §8: prompts are versioned)
    config:        from get_config(); default get_config() (api mode)
    timeout:       seconds per attempt; default from config (60 api, 300 local)
    Raises LLMError on failure, after logging each attempt.
    """
    _verify_built(built)
    if not isinstance(system_prompt, str) or "json" not in system_prompt.lower():
        raise LLMError("system prompt must mention JSON (required by the API's JSON mode)")
    if not prompt_id:
        raise LLMError("prompt_id is required so every call can be traced to a prompt version")
    config = config or get_config()
    mode = check_config(config)
    timeout = timeout or config.get("timeout") or DEFAULT_TIMEOUT[mode]

    url = f"{config['base_url']}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if config.get("api_key"):
        headers["Authorization"] = f"Bearer {config['api_key']}"
    body = {
        "model": config["model"],
        "messages": [{"role": "system", "content": system_prompt},
                     {"role": "user", "content": _canonical(built["payload"])}],
        "response_format": {"type": "json_object"},
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    for key, value in (config.get("extra_body") or {}).items():
        body.setdefault(key, value)  # cannot replace the model, messages or JSON mode
    base = {"task": built["payload"]["task"], "payload_sha256": built["sha256"], "prompt_id": prompt_id,
            "prompt_sha256": _sha256(system_prompt), "mode": mode, "requested_model": config["model"],
            "base_url": config["base_url"], "temperature": temperature, "max_tokens": max_tokens,
            "extra_body": config.get("extra_body")}

    for attempt in range(1, max_attempts + 1):
        start = time.monotonic()
        try:
            output, info = _parse(transport(url, headers, body, timeout))
        except LLMError as err:
            _log(call_log, {**base, "attempt": attempt, "status": "error", "error": str(err),
                            "seconds": round(time.monotonic() - start, 3)})
            if attempt == max_attempts or not err.retryable:
                raise
            continue
        record = {**base, "attempt": attempt, "status": "ok", "seconds": round(time.monotonic() - start, 3),
                  **info, "output": output}
        _log(call_log, record)
        return {"output": output, "record": record}
