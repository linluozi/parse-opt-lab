#!/usr/bin/env python3
"""Benchmark parse.parse() on a real corpus.

Two workloads:

* ``corpus``   -- the real dpkg ``status`` line corpus (3 scales), the same
                  format strings applied to every line, which is how a log /
                  record parser is normally used.
* ``distinct`` -- 10,000 pairwise-distinct format strings, each parsed exactly
                  once.  This is the cache-miss envelope: it measures what the
                  optimisation costs when it cannot help.

Every timing sample is written to ``raw/<tag>-<scale>-<i>.json``; only the
aggregate lives in ``<tag>.json``.  Timing uses ``time.perf_counter()``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

SEED = 20261114
FORMATS = {
    "Package": "Package: {name}",
    "Version": "Version: {version}",
    "Depends": "Depends: {deps}",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_corpus(path: Path, limit: int) -> list[tuple[str, str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines()[:limit]:
        for key, fmt in FORMATS.items():
            if line.startswith(key + ": "):
                rows.append((fmt, line))
                break
    if not rows:
        raise SystemExit(f"no usable lines in {path}")
    return rows


def run_corpus(parse_mod, rows: list[tuple[str, str]]) -> tuple[int, int]:
    matched = 0
    payload = 0
    for fmt, line in rows:
        r = parse_mod.parse(fmt, line)
        if r is not None:
            matched += 1
            payload += len(r.fixed) + len(r.named)
    return matched, payload


def build_distinct_formats(n: int) -> list[tuple[str, str]]:
    rng = random.Random(SEED)
    specs = ["", ":d", ":.2f", ":>8", ":w", ":.3f", ":^10"]
    seen: set[str] = set()
    cases: list[tuple[str, str]] = []
    i = 0
    while len(cases) < n:
        name = f"field_{i}_{rng.randrange(10**9):09d}"
        spec = specs[i % len(specs)]
        literal = "".join(rng.choice("abcXYZ_-. ") for _ in range(1 + i % 12))
        fmt = f"{literal}{{{name}{spec}}} tail"
        if spec in ("", ":w", ":>8", ":^10"):
            value = f"v{i}"
        elif spec == ":d":
            value = str(i)
        else:
            value = f"{i}.5"
        string = f"{literal}{value} tail"
        key = hashlib.sha256((fmt + "\x00" + string).encode()).hexdigest()
        i += 1
        if key in seen:
            continue
        seen.add(key)
        cases.append((fmt, string))
    return cases


def run_distinct(parse_mod, cases: list[tuple[str, str]]) -> tuple[int, int]:
    matched = 0
    payload = 0
    for fmt, string in cases:
        r = parse_mod.parse(fmt, string)
        if r is not None:
            matched += 1
            payload += len(r.fixed) + len(r.named)
    return matched, payload


def cost_split(parse_mod, rows: list[tuple[str, str]], n: int = 3000) -> dict:
    """Baseline only: construction+compile cost vs match cost."""
    fmts = [rows[i % len(rows)][0] for i in range(n)]
    t0 = time.perf_counter()
    for fmt in fmts:
        p = parse_mod.Parser(fmt)
        p._match_re  # force lazy regex compilation, as one parse() call does
    construct = time.perf_counter() - t0

    parser = parse_mod.Parser(fmts[0])
    parser.parse(rows[0][1])  # compile once
    strings = [rows[i % len(rows)][1] for i in range(n)]
    t0 = time.perf_counter()
    for string in strings:
        parser.parse(string)
    match = time.perf_counter() - t0
    total = construct + match
    return {
        "iterations": n,
        "construct_compile_s": round(construct, 6),
        "match_s": round(match, 6),
        "construct_compile_share": round(construct / total, 4),
        "match_share": round(match / total, 4),
    }


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="tree that contains the parse/ package")
    ap.add_argument("--tag", required=True, help="baseline or optimized")
    ap.add_argument("--out", required=True, help="output directory (usually benchmark/)")
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--scales", default="500,1500,3000")
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--distinct", type=int, default=10000)
    ap.add_argument("--tests-command", default="")
    ap.add_argument("--tests-summary", default="")
    args = ap.parse_args()

    src = Path(args.src).resolve()
    sys.path.insert(0, str(src))
    import parse as parse_mod  # noqa: PLC0415

    if not Path(parse_mod.__file__).resolve().is_relative_to(src):
        raise SystemExit(f"imported parse from {parse_mod.__file__}, expected under {src}")

    out = Path(args.out).resolve()
    (out / "raw").mkdir(parents=True, exist_ok=True)
    corpus_path = Path(args.corpus).resolve()
    all_rows = load_corpus(corpus_path, max(int(s) for s in args.scales.split(",")))
    scales = [int(s) for s in args.scales.split(",")]

    scale_results = {}
    for scale in scales:
        rows = all_rows[:scale]
        expected = run_corpus(parse_mod, rows)
        for _ in range(args.warmup):
            assert run_corpus(parse_mod, rows) == expected
        samples = []
        for i in range(args.samples):
            t0 = time.perf_counter()
            got = run_corpus(parse_mod, rows)
            elapsed = time.perf_counter() - t0
            assert got == expected, (got, expected)
            raw = {
                "impl": args.tag,
                "workload": "corpus",
                "scale": scale,
                "sample": i,
                "elapsed_s": round(elapsed, 9),
                "lines": len(rows),
                "matched": got[0],
                "payload": got[1],
            }
            (out / "raw" / f"{args.tag}-corpus-{scale}-{i}.json").write_text(
                json.dumps(raw, indent=1) + "\n"
            )
            samples.append(elapsed)
        median = statistics.median(samples)
        sd = statistics.stdev(samples) if len(samples) > 1 else 0.0
        scale_results[str(scale)] = {
            "lines": len(rows),
            "samples_s": [round(s, 9) for s in samples],
            "median_s": round(median, 9),
            "p25_s": round(pct(samples, 0.25), 9),
            "p75_s": round(pct(samples, 0.75), 9),
            "rsd": round(sd / median, 4) if median else None,
        }

    distinct_cases = build_distinct_formats(args.distinct)
    expected_d = run_distinct(parse_mod, distinct_cases)
    run_distinct(parse_mod, distinct_cases)  # warmup
    d_samples = []
    for i in range(args.samples):
        t0 = time.perf_counter()
        got = run_distinct(parse_mod, distinct_cases)
        elapsed = time.perf_counter() - t0
        assert got == expected_d
        raw = {
            "impl": args.tag,
            "workload": "distinct",
            "scale": len(distinct_cases),
            "sample": i,
            "elapsed_s": round(elapsed, 9),
            "distinct_inputs": len(distinct_cases),
            "sha256_set": hashlib.sha256(
                "\n".join(sorted(
                    hashlib.sha256((f + "\x00" + s).encode()).hexdigest()
                    for f, s in distinct_cases
                )).encode()
            ).hexdigest(),
        }
        (out / "raw" / f"{args.tag}-distinct-{len(distinct_cases)}-{i}.json").write_text(
            json.dumps(raw, indent=1) + "\n"
        )
        d_samples.append(elapsed)

    distinct_result = {
        "inputs": len(distinct_cases),
        "samples_s": [round(s, 9) for s in d_samples],
        "median_s": round(statistics.median(d_samples), 9),
        "p25_s": round(pct(d_samples, 0.25), 9),
        "p75_s": round(pct(d_samples, 0.75), 9),
        "matched": expected_d[0],
    }

    try:
        commit = subprocess.run(
            ["git", "-C", str(src), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        commit = "unknown"

    payload = {
        "impl": args.tag,
        "upstream": "r1chardj0n3s/parse",
        "upstream_commit": commit,
        "src": str(src),
        "command": " ".join([sys.executable] + sys.argv),
        "python": platform.python_version(),
        "cpu": next(
            (ln.split(":", 1)[1].strip() for ln in Path("/proc/cpuinfo").read_text().splitlines()
             if ln.startswith("model name")), "unknown"),
        "mem_total_kb": next(
            (int(ln.split()[1]) for ln in Path("/proc/meminfo").read_text().splitlines()
             if ln.startswith("MemTotal")), 0),
        "seed": SEED,
        "corpus": str(corpus_path),
        "corpus_bytes": corpus_path.stat().st_size,
        "corpus_sha256": sha256_file(corpus_path),
        "corpus_lines_total": len(all_rows),
        "formats": FORMATS,
        "warmup": args.warmup,
        "samples": args.samples,
        "upstream_tests": {
            "command": args.tests_command,
            "summary": args.tests_summary,
        },
        "scales": scale_results,
        "distinct_envelope": distinct_result,
    }
    if args.tag == "baseline":
        payload["cost_split"] = cost_split(parse_mod, all_rows, n=3000)
    (out / f"{args.tag}.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({k: payload[k] for k in ("impl", "scales", "distinct_envelope")}, indent=2))
    if "cost_split" in payload:
        print(json.dumps(payload["cost_split"], indent=2))


if __name__ == "__main__":
    main()
