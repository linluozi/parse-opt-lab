#!/usr/bin/env python3
"""Run the differential corpus against one parse tree and print canonical JSONL.

The same script is executed twice by ``tests/test_diff.py`` (once with the
pristine upstream tree on ``sys.path``, once with the patched tree).  Because
both output streams are produced by identical code, a byte comparison of the
two stdout streams is a true differential test.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

SEED = 20261114
HERE = Path(__file__).resolve().parent
CORPUS = HERE.parent / "benchmark" / "corpus" / "dpkg-status-lines.txt"

CAP = lambda s: s.upper()  # noqa: E731
PREFIX = lambda s: "x" + s  # noqa: E731
REV = lambda s: s[::-1]  # noqa: E731


def _double(s):
    return str(int(s) * 2)


EXTRA_SETS = {
    "plain": None,
    "upper": {"w": CAP},
    "prefix": {"w": PREFIX},
    "reverse": {"w": REV},
    "double": {"z": _double},
    "upper_reverse": {"w": CAP, "z": _double},
    "prefix_reverse": {"w": PREFIX, "z": REV},
}

FORMAT_LINES = {
    "Package": "Package: {name}",
    "Version": "Version: {version}",
    "Depends": "Depends: {deps}",
}


def real_cases() -> list[tuple[str, str, str]]:
    rows = []
    for line in CORPUS.read_text(encoding="utf-8").splitlines()[:400]:
        for key, fmt in FORMAT_LINES.items():
            if line.startswith(key + ": "):
                rows.append((fmt, line, "plain"))
                break
    return rows


def generated_cases(rng: random.Random, n: int) -> list[tuple[str, str, str]]:
    out = []
    for i in range(n):
        w = "".join(rng.choice("abcXYZ") for _ in range(1 + i % 9))
        num = str(rng.randrange(10**6))
        name = f"f{i}"
        kind = i % 12
        if kind == 0:
            out.append(("{name}", name, "plain"))
        elif kind == 1:
            out.append(("{name} {name}", f"{name} {name}", "plain"))
        elif kind == 2:
            out.append(("{a.b}", f"nested{i}", "plain"))
        elif kind == 3:
            out.append(("{word:w}!", w, "upper"))
        elif kind == 4:
            out.append(("{word:w}-{num:z}", f"{w}-{num}", "double"))
        elif kind == 5:
            out.append(("<{num:d}>", f"<{num}>", "double"))
        elif kind == 6:
            out.append(("{num:d}", f"-{num}", "plain"))
        elif kind == 7:
            out.append(("prefix {word:w} suffix", f"prefix {w} suffix", "reverse"))
        elif kind == 8:
            out.append(("{v:.2f}", f"{i}.25", "plain"))
        elif kind == 9:
            out.append(("{x}::{y}", f"{name}::{num}", "plain"))
        elif kind == 10:
            out.append(("{名前}", f"名{i}", "plain"))
        else:
            out.append(("{{{name}}}", "{" + name + "}", "plain"))
    return out


def boundary_cases() -> list[tuple[str, str, str]]:
    cases = [
        ("", "", "plain"),
        ("{}", "", "plain"),
        ("{}", " ", "plain"),
        ("{}", "🙂中é", "plain"),
        ("{}", "a" * 2000, "plain"),
        ("{x}", "\n\t\r", "plain"),
        ("{x}", "nan", "plain"),
        ("{x}", "None", "plain"),
        ("{{}}", "{}", "plain"),
        ("{{{{", "{{", "plain"),
        ("{x:05d}", "00042", "plain"),
        ("{x:d}", "-17", "plain"),
        ("{x:g}", "1e-9", "plain"),
        ("{x:.10f}", "3.1415926536", "plain"),
        ("{x}", "", "upper"),
        ("{x}", "MiXeD", "upper"),
        ("{x} {x}", "abc abc", "plain"),
        ("{x} {x}", "abc abd", "plain"),
        ("{word}", "abc", "plain"),
        ("{word}", "abc", "upper"),
        ("{word}", "abc", "prefix"),
        ("{word}", "abc", "reverse"),
        ("{num}", "21", "double"),
        ("{num}", "21", "plain"),
        ("{word} {num}", "abc 21", "upper_reverse"),
        ("{word} {num}", "abc 21", "prefix_reverse"),
        ("{a.b} {a[b]}", "x y", "plain"),
        ("{a} {a}", "", "plain"),
        ("{a} {a:d}", "1 1", "plain"),
        ("{a:d} {a:w}", "1 1", "plain"),
        ("{", "", "plain"),
        ("}", "", "plain"),
        ("{} {}", "onlyone", "plain"),
        ("{x:>}", "abc", "plain"),
        ("{x:.}", "abc", "plain"),
        ("{0}", "", "plain"),
        ("{-x}", "", "plain"),
        ("{x-y}", "", "plain"),
        ("{x.y.z}", "", "plain"),
    ]
    return cases


def build_cases() -> list[tuple[str, str, str]]:
    rng = random.Random(SEED)
    cases = real_cases() + generated_cases(rng, 700) + boundary_cases()
    # extra_types identity must be part of the cache key: same format, same
    # string, different converters.
    for key in EXTRA_SETS:
        cases.append(("{word:w}", "abc", key))
        cases.append(("{word:w} {num:z}", "abc 7", key))
    return cases


def canon(result) -> dict:
    return {
        "fixed": [repr(v) for v in result.fixed],
        "named": {k: repr(v) for k, v in result.named.items()},
        "spans": {str(k): [int(v[0]), int(v[1])] for k, v in result.spans.items()},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    args = ap.parse_args()
    src = str(Path(args.src).resolve())
    sys.path.insert(0, src)
    import parse  # noqa: PLC0415

    if not Path(parse.__file__).resolve().is_relative_to(Path(src)):
        raise SystemExit(f"wrong parse import: {parse.__file__}")

    for i, (fmt, string, extra_key) in enumerate(build_cases()):
        extra = EXTRA_SETS[extra_key]
        try:
            r = parse.parse(fmt, string, extra_types=extra)
            if r is None:
                out = {"i": i, "none": True}
            else:
                out = {"i": i, "ok": canon(r)}
        except Exception as exc:  # noqa: BLE001
            out = {"i": i, "err": [type(exc).__name__, str(exc)]}
        print(json.dumps(out, sort_keys=True, ensure_ascii=True))


if __name__ == "__main__":
    main()
