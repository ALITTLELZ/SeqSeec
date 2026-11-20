# File: tests/test_headers.py
# Version: 0.1.1
# Last modified: 2026-11-20 (XD)
# Change: Also check scripts under demo/.
"""Every .py file must start with File / Version / Last modified / Change lines."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
HEADER = re.compile(
    r"\A# File: (?P<file>\S+)\n"
    r"# Version: \d+\.\d+\.\d+\n"
    r"# Last modified: \d{4}-\d{2}-\d{2} \(.+\)\n"
    r"# Change: .+\n"
)


def python_files():
    for d in ("seqseec", "tests", "eval", "scripts", "demo"):
        yield from (ROOT / d).rglob("*.py") if (ROOT / d).exists() else []


def test_every_script_has_header():
    bad = []
    for path in python_files():
        if "out" in path.relative_to(ROOT).parts:
            continue
        m = HEADER.match(path.read_text(encoding="utf8"))
        rel = path.relative_to(ROOT).as_posix()
        if not m or m.group("file") != rel:
            bad.append(rel)
    assert not bad, f"Missing or wrong version header: {bad}"
