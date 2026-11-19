# File: scripts/check_llm_live.py
# Version: 0.1.0
# Last modified: 2026-11-19 (XD)
# Change: One-call live check of the DeepSeek API through payload.py + llm.py, using a synthetic note.
"""Send ONE synthetic lab note to the real LLM API and print what came back.

Needs DEEPSEEK_API_KEY in the environment or in .env (repo root). Costs a
fraction of a cent. Only the synthetic note below leaves the machine.

Usage (from the repo root):
  python scripts/check_llm_live.py
Writes to audit/payload_audit.jsonl and audit/llm_calls.jsonl (both git-ignored).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from seqseec.llm import LLMError, call_llm, get_config  # noqa: E402
from seqseec.payload import build_payload  # noqa: E402

NOTE = ("SYNTHETIC TEST NOTE. Total RNA from HeLa cells was poly(A)-selected and libraries were built with "
        "the NEBNext Ultra II Directional RNA Library Prep Kit, then sequenced 2x100 on a NovaSeq 6000.")
PROMPT = ('Read the lab notes in parts.notes and answer in JSON: {"kit": string or null, '
          '"read_layout": "PE" or "SE" or null}. Use only what the notes state.')


def main():
    config = get_config()
    if not config["api_key"]:
        sys.exit("No DEEPSEEK_API_KEY found in the environment or .env; nothing was sent.")
    built = build_payload("extract", notes=NOTE)
    try:
        result = call_llm(built, PROMPT, "live_check_v1", config=config)
    except LLMError as err:
        sys.exit(f"LIVE CHECK FAILED: {err}\nDetails per attempt are in audit/llm_calls.jsonl.")
    rec = result["record"]
    print("LIVE CHECK OK")
    print(f"  requested model : {rec['requested_model']}")
    print(f"  returned model  : {rec['response_model']}")
    print(f"  attempts        : {rec['attempt']}")
    print(f"  tokens          : {rec['usage']}")
    print(f"  output          : {json.dumps(result['output'])}")
    print("Please paste these lines into the PR or group chat and note the date.")


if __name__ == "__main__":
    main()
