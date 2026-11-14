#!/usr/bin/env python3
"""Print the gate table from benchmark/{baseline,optimized}.json."""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    base = json.loads((HERE / "baseline.json").read_text())
    opt = json.loads((HERE / "optimized.json").read_text())
    ratios = {}
    print(f"{'scale':>8} {'baseline ms':>12} {'optimized ms':>13} {'speedup':>8}")
    for scale in base["scales"]:
        b = base["scales"][scale]["median_s"] * 1000
        o = opt["scales"][scale]["median_s"] * 1000
        ratios[scale] = b / o
        print(f"{scale:>8} {b:>12.3f} {o:>13.3f} {b / o:>7.2f}x")
    ordered = sorted(ratios, key=int)
    median = sorted(ratios.values())[len(ratios) // 2]
    large = ratios[ordered[-1]]
    env_b = base["distinct_envelope"]["median_s"]
    env_o = opt["distinct_envelope"]["median_s"]
    print()
    print(f"G3  median speedup       : {median:.2f}x  (>= 1.15x: {median >= 1.15})")
    print(f"G3b real-corpus speedup  : {median:.2f}x  (>= 1.15x: {median >= 1.15})")
    print(f"G4  largest scale        : {large:.2f}x  (>= 0.95x: {large >= 0.95})")
    print(f"    miss-path envelope   : {env_b / env_o:.3f}x  (>= 0.95x: {env_b / env_o >= 0.95})")
    return 0 if median >= 1.15 and large >= 0.95 and env_b / env_o >= 0.95 else 1


if __name__ == "__main__":
    raise SystemExit(main())
