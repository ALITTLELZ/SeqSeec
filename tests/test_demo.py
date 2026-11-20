# File: tests/test_demo.py
# Version: 0.1.0
# Last modified: 2026-11-20 (XD)
# Change: The replay page rebuilds byte-for-byte, shows the named eval run whatever the file times, and holds no paths.
import importlib.util
import os
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_replay", ROOT / "demo" / "build_replay.py")
build_replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_replay)


def test_rebuild_matches_committed_page():
    page, _ = build_replay.build()
    committed = (ROOT / "demo" / "index.html").read_bytes().replace(b"\r\n", b"\n").decode("utf8")
    assert page == committed, "demo/index.html is stale: run python demo/build_replay.py"


def test_named_eval_run_shown_whatever_the_file_times():
    results = sorted((ROOT / "eval" / "results").glob("cases_heldout_*.json"))
    old = {p: p.stat().st_mtime for p in results}
    try:
        for i, p in enumerate(results):  # make every other file look newer than the named one
            os.utime(p, (0, 10**9 + (0 if p.name in build_replay.EVAL_RESULT else 1000 + i)))
        _, payload = build_replay.build()
    finally:
        for p, t in old.items():
            os.utime(p, (t, t))
    assert payload["eval"]["file"] == build_replay.EVAL_RESULT
    assert payload["eval"]["meta"]["commit"] in build_replay.EVAL_RESULT


def test_page_has_no_paths_or_reads():
    page, _ = build_replay.build()
    assert not re.search(r"[A-Za-z]:\\\\|/Users/|/home/|/nfs/", page)
    assert not re.search(r"[ACGT]{30,}", page)


def test_out_option_writes_lf(tmp_path):
    out = tmp_path / "page.html"
    build_replay.main(["--out", str(out)])
    assert b"\r\n" not in out.read_bytes()
