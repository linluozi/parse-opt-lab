#!/usr/bin/env python3
"""Differential test: pristine upstream parse vs patched parse.

Both trees are imported in *separate* subprocesses (``tests/_probe.py``) so the
two ``parse`` modules never share state.  The two JSONL streams must be
byte-identical.

Run directly::

    python tests/test_diff.py --baseline /path/to/upstream --optimized .

The distinct-sample count is reported after sha256 de-duplication, not as a
loop count.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _probe import EXTRA_SETS, build_cases  # noqa: E402


def distinct_count(cases) -> int:
    seen = set()
    for fmt, string, extra_key in cases:
        blob = json.dumps(
            [fmt, string, extra_key, sorted(EXTRA_SETS[extra_key] or {})],
            ensure_ascii=False,
            sort_keys=True,
        )
        seen.add(hashlib.sha256(blob.encode()).hexdigest())
    return len(seen)


def run_probe(src: Path) -> bytes:
    proc = subprocess.run(
        [sys.executable, str(HERE / "_probe.py"), "--src", str(src)],
        capture_output=True,
        check=True,
    )
    return proc.stdout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True, type=Path)
    ap.add_argument("--optimized", required=True, type=Path)
    args = ap.parse_args()

    cases = build_cases()
    distinct = distinct_count(cases)
    base = run_probe(args.baseline)
    opt = run_probe(args.optimized)

    base_lines = base.splitlines()
    opt_lines = opt.splitlines()
    mismatches = []
    for i, (a, b) in enumerate(zip(base_lines, opt_lines)):
        if a != b:
            mismatches.append(i)
    if len(base_lines) != len(opt_lines):
        mismatches.append(-1)

    kinds = {"ok": 0, "none": 0, "err": 0}
    for line in base_lines:
        rec = json.loads(line)
        kinds["ok" if "ok" in rec else "none" if rec.get("none") else "err"] += 1

    print(f"cases generated      : {len(cases)}")
    print(f"distinct after sha256: {distinct}")
    print(f"results (ok/none/err): {kinds['ok']}/{kinds['none']}/{kinds['err']}")
    print(f"byte-identical lines : {len(base_lines) - len(mismatches)}/{len(base_lines)}")
    print(f"mismatches           : {len(mismatches)}")
    if mismatches:
        for i in mismatches[:5]:
            print(f"  first mismatch at line {i}")
        return 1
    if distinct < 1000:
        print("FAIL: fewer than 1000 distinct inputs")
        return 1
    print("PASS: 0 mismatches, >=1000 distinct inputs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
