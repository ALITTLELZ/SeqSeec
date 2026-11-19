# File: seqseec/cli.py
# Version: 0.1.1
# Last modified: 2026-11-19 (Track B)
# Change: Steps 2-3 are built: updated the documents option group help.
"""SeqSeec command line.

  seqseec run --notes notes.txt [--r1 R1.fq.gz --r2 R2.fq.gz --gtf genes.gtf --transcripts tx.fa]
  seqseec run --notes notes.txt --llm local            # model server on this machine (Ollama)
  seqseec run --llm none --expected RF --data-call RF  # no LLM at all
  seqseec settings RF --layout SE

Exit codes: 0 report written; 1 report written but a step failed; 2 bad arguments or setup.
The pipeline itself is in seqseec/pipeline.py; to add an option, see its docstring.
"""
import argparse
import json
import os
import sys

from seqseec import __version__
from seqseec.llm import LLMError, check_config, get_config
from seqseec.pipeline import LLM_MODES, format_report, run_pipeline
from seqseec.settings import get_settings

ORIENTATION_CHOICES = ("FR", "RF", "UNSTRANDED")
DATA_CALL_CHOICES = ORIENTATION_CHOICES + ("INCONCLUSIVE", "INVALID")


def _upper(value):
    return value.strip().upper().replace("_", "-")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="seqseec",
        description="Work out RNA-seq library strandedness from lab notes and reads, "
                    "and the matching downstream tool settings.")
    parser.add_argument("--version", action="version", version=f"seqseec {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    run = sub.add_parser("run", help="run the whole pipeline and print one report",
                         description="Run steps 1-7 once. Give notes, reads, or both.")
    g = run.add_argument_group("notes and LLM (step 1)")
    g.add_argument("--notes", metavar="FILE", help="lab notes as a text file ('-' reads standard input)")
    g.add_argument("--llm", choices=LLM_MODES, default="api",
                   help="api: DeepSeek API, notes leave the machine (default); local: model server on this "
                        "machine, e.g. Ollama, nothing leaves the machine; none: no LLM, notes are not read")
    g.add_argument("--model", help="model name; overrides SEQSEEC_LLM_MODEL / SEQSEEC_LOCAL_MODEL")
    g.add_argument("--base-url", help="server URL; overrides SEQSEEC_LLM_BASE_URL / SEQSEEC_LOCAL_BASE_URL")
    g.add_argument("--env-file", default=".env", help="file with keys and settings (default .env)")

    g = run.add_argument_group("documents (steps 2-3: kit registry lookup)")
    g.add_argument("--expected", type=_upper, choices=ORIENTATION_CHOICES, metavar="{FR,RF,UNSTRANDED}",
                   help="skip the kit lookup and use this orientation from the kit documents")

    g = run.add_argument_group("reads (step 4; runs locally, reads never leave the machine)")
    g.add_argument("--r1", metavar="FASTQ", help="read 1 (or the only read file for single-end)")
    g.add_argument("--r2", metavar="FASTQ", help="read 2 (paired-end)")
    g.add_argument("--gtf", metavar="FILE", help="annotation matching the reads' species")
    g.add_argument("--transcripts", metavar="FASTA", help="transcript sequences matching the GTF")
    g.add_argument("--nreads", type=int, default=200000, help="reads to sample (default 200000)")
    g.add_argument("--index-name", default="kallisto_index",
                   help="name of the cached kallisto index; use one name per reference")
    g.add_argument("--tools-env", default="seqseec-tools", help="conda env with the strandedness tools")
    g.add_argument("--data-call", type=_upper, choices=DATA_CALL_CHOICES, metavar="CALL",
                   help=f"skip the data check and use this call from an earlier check: {', '.join(DATA_CALL_CHOICES)}")
    g.add_argument("--layout", type=_upper, choices=("PE", "SE"), metavar="{PE,SE}",
                   help="read layout, if the reads and notes do not show it")

    g = run.add_argument_group("output")
    g.add_argument("--format", choices=("text", "json"), default="text", help="report format on screen")
    g.add_argument("--out", metavar="FILE", help="also write the full report as JSON to this file")
    g.add_argument("--audit-dir", default="audit", help="folder for the payload and LLM call logs")

    st = sub.add_parser("settings", help="print the downstream settings for an orientation")
    st.add_argument("orientation", type=_upper, help="FR, RF, UNSTRANDED or fr-firststrand / fr-secondstrand / fr-unstranded")
    st.add_argument("--layout", type=_upper, choices=("PE", "SE"), default="PE", metavar="{PE,SE}")
    return parser


def _read_notes(path):
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf8") as f:
        return f.read()


def _llm_config(args):
    if args.llm == "none":
        return None
    config = get_config(args.env_file, mode=args.llm)
    if args.model:
        config["model"] = args.model
    if args.base_url:
        config["base_url"] = args.base_url.rstrip("/")
    return config


def _run(args, parser, stages):
    if not (args.notes or args.r1 or args.data_call or args.expected):
        parser.error("give at least one of --notes, --r1, --data-call or --expected")
    if args.r2 and not args.r1:
        parser.error("--r2 needs --r1")
    if args.r1 and not (args.gtf and args.transcripts):
        parser.error("--r1 needs --gtf and --transcripts")
    if args.r1 and args.data_call:
        parser.error("give either reads (--r1) or --data-call, not both")
    for name in ("r1", "r2", "gtf", "transcripts"):
        path = getattr(args, name)
        if path and not os.path.exists(path):
            parser.error(f"--{name}: file not found: {path}")
    try:
        notes = _read_notes(args.notes) if args.notes else None
    except OSError as err:
        parser.error(f"--notes: {err}")

    config = _llm_config(args)
    if config and notes:
        try:
            check_config(config)  # fail before any step runs
        except LLMError as err:
            hint = (" Or run with --llm local or --llm none." if args.llm == "api" else "")
            print(f"seqseec: {err}.{hint}", file=sys.stderr)
            return 2

    options = {"notes": notes, "llm": args.llm, "llm_config": config, "expected": args.expected,
               "r1": args.r1, "r2": args.r2, "gtf": args.gtf, "transcripts": args.transcripts,
               "nreads": args.nreads, "index_name": args.index_name, "tools_env": args.tools_env,
               "data_call": args.data_call, "layout": args.layout, "audit_dir": args.audit_dir}
    report = run_pipeline(options, stages=stages)
    if args.llm == "local" and any("could not reach" in e or "not found" in e for e in report["errors"]):
        report["errors"].append(f"Is the local model server running at {config['base_url']}? "
                                f"For Ollama: `ollama serve`, then `ollama pull {config['model']}`.")

    if args.out:
        folder = os.path.dirname(args.out)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(args.out, "w", encoding="utf8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.format == "json" else format_report(report))
    return 0 if report["ok"] else 1


def _settings(args, parser):
    try:
        s = get_settings(args.orientation, args.layout)
    except ValueError as err:
        parser.error(str(err))
    print(f"{s['orientation']} ({s['library_type']}), {s['layout']}; "
          f"RSeQC dominant pattern: {s['rseqc_dominant'] or 'none (about even)'}")
    for tool, t in s["tools"].items():
        print(f"  {tool:<14}{t['setting']}")
    return 0


def main(argv=None, *, stages=None):
    """Entry point for `seqseec` and `python -m seqseec`. stages: test fakes passed to run_pipeline."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return _run(args, parser, stages)
    return _settings(args, parser)


if __name__ == "__main__":
    sys.exit(main())
