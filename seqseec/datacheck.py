# File: seqseec/datacheck.py
# Version: 0.1.0
# Last modified: 2026-11-08 (Track B)
# Change: Run how_are_we_stranded_here in a space-free staging dir; parse its RSeQC output; apply data-call rules.
"""Step 4: local data check.

Runs ``check_strandedness`` (how_are_we_stranded_here) in the separate
``seqseec-tools`` conda environment and returns ONLY a numeric summary.
Reads, file paths and sequences never appear in the returned dict, so the
result is safe to pass to the LLM payload builder.

Thresholds mirror how_are_we_stranded_here (commit e6ce74d):
  fraction of explainable reads > 0.9 in one direction -> stranded
  max fraction < 0.6                                    -> unstranded
  otherwise                                             -> inconclusive
The tool itself only *warns* when more than half of the reads cannot be
assigned; SeqSeec is stricter and marks such a check INVALID (see plan §5).
"""
import os
import re
import shutil
import subprocess
import tempfile

STRANDED_MIN = 0.9
UNSTRANDED_MAX = 0.6
FAILED_MAX = 0.5

# RSeQC pattern for "read 1 on the transcript's strand", by layout.
FORWARD_PATTERN = {"PE": "1++,1--,2+-,2-+", "SE": "++,--"}
REVERSE_PATTERN = {"PE": "1+-,1-+,2++,2--", "SE": "+-,-+"}

_FRACTION = re.compile(r'Fraction of reads explained by "([^"]+)":\s*([0-9.]+)')
_FAILED = re.compile(r"Fraction of reads failed to determine:\s*([0-9.]+)")


def parse_infer_experiment(text):
    """Parse RSeQC infer_experiment.py output (as printed by check_strandedness).

    Returns {"layout": "PE"|"SE", "failed": float, "forward": float, "reverse": float}.
    Raises ValueError if the expected lines are missing.
    """
    if "PairEnd Data" in text:
        layout = "PE"
    elif "SingleEnd Data" in text:
        layout = "SE"
    else:
        raise ValueError("infer_experiment output has no layout line")
    failed = _FAILED.search(text)
    fractions = dict(_FRACTION.findall(text))
    fwd, rev = FORWARD_PATTERN[layout], REVERSE_PATTERN[layout]
    if failed is None or fwd not in fractions or rev not in fractions:
        raise ValueError("infer_experiment output is missing fraction lines")
    return {
        "layout": layout,
        "failed": float(failed.group(1)),
        "forward": float(fractions[fwd]),
        "reverse": float(fractions[rev]),
    }


def call_orientation(parsed):
    """Apply the data-call rules to a parsed result.

    Returns a dict with call in {"FR", "RF", "UNSTRANDED", "INCONCLUSIVE", "INVALID"}.
    FR = read 1 on the transcript strand (fr-secondstrand); RF = dUTP-style (fr-firststrand).
    """
    fwd, rev, failed = parsed["forward"], parsed["reverse"], parsed["failed"]
    explained = fwd + rev
    summary = {
        "layout": parsed["layout"],
        "failed_fraction": failed,
        "forward_fraction": fwd,
        "reverse_fraction": rev,
    }
    if failed > FAILED_MAX or explained <= 0:
        return {**summary, "call": "INVALID",
                "reason": "More than half of the reads could not be assigned to a strand; "
                          "check that the reference, annotation and species match the reads."}
    fwd_pct, rev_pct = fwd / explained, rev / explained
    summary.update(forward_share=round(fwd_pct, 4), reverse_share=round(rev_pct, 4))
    if fwd_pct > STRANDED_MIN:
        return {**summary, "call": "FR", "reason": "Over 90% of assignable reads have read 1 on the transcript strand."}
    if rev_pct > STRANDED_MIN:
        return {**summary, "call": "RF", "reason": "Over 90% of assignable reads have read 1 antisense to the transcript."}
    if max(fwd_pct, rev_pct) < UNSTRANDED_MAX:
        return {**summary, "call": "UNSTRANDED", "reason": "Neither direction explains 60% of assignable reads."}
    return {**summary, "call": "INCONCLUSIVE",
            "reason": "Dominant direction is between 60% and 90%; check for contamination or low quality."}


INDEX_CACHE = os.path.expanduser("~/.cache/seqseec/kallisto")


def _stage(src, stage_dir, name):
    """Symlink an input into the staging dir under a space-free name, keeping its extensions."""
    base = os.path.basename(src)
    ext = base[base.index("."):] if "." in base else ""
    dst = os.path.join(stage_dir, name + ext.replace(" ", "_"))
    os.symlink(os.path.abspath(src), dst)
    return os.path.basename(dst)


def run_check_strandedness(gtf, transcripts, reads_1, reads_2=None, index_name="kallisto_index",
                           env="seqseec-tools", nreads=200000, keep_workdir=False):
    """Run check_strandedness locally and return the numeric summary from call_orientation().

    how_are_we_stranded_here builds shell commands from its arguments, so any
    space in a path breaks it. We therefore symlink every input into a fresh,
    space-free staging directory and run the tool there. The kallisto index is
    cached under ~/.cache/seqseec/kallisto/<index_name> and reused across runs;
    use a different index_name for each reference.

    Paths are used only to build the local command; they are not in the returned dict.
    """
    stage = tempfile.mkdtemp(prefix="seqseec_hawsh_")
    if " " in stage:
        raise RuntimeError(f"Temporary directory path contains a space: {stage}")
    os.makedirs(INDEX_CACHE, exist_ok=True)
    index_path = os.path.join(INDEX_CACHE, index_name) if " " not in INDEX_CACHE else os.path.join(stage, index_name)
    cmd = ["conda", "run", "-n", env, "check_strandedness",
           "--gtf", _stage(gtf, stage, "annotation"),
           "--transcripts", _stage(transcripts, stage, "transcripts"),
           "--reads_1", _stage(reads_1, stage, "reads_1"),
           "--kallisto_index", index_path, "--nreads", str(nreads)]
    if reads_2:
        cmd += ["--reads_2", _stage(reads_2, stage, "reads_2")]
    try:
        proc = subprocess.run(cmd, cwd=stage, capture_output=True, text=True)
    finally:
        if not keep_workdir:
            shutil.rmtree(stage, ignore_errors=True)
    output = proc.stdout + "\n" + proc.stderr
    try:
        result = call_orientation(parse_infer_experiment(output))
    except ValueError:
        tail = "\n".join(output.strip().splitlines()[-5:])
        raise RuntimeError(f"check_strandedness failed (exit {proc.returncode}):\n{tail}") from None
    result["tool"] = "how_are_we_stranded_here@e6ce74d"
    result["nreads_requested"] = nreads
    return result
