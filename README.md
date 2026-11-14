# parse-opt-lab

`parse` turns a format string such as `"Package: {name}"` into values. Its
module-level `parse.parse()` / `parse.search()` rebuild the `Parser` and
re-compile the generated regex **on every call**; this patch reuses a
semantics-keyed LRU cache of `Parser` objects and measures **2.47x** on real
`/var/lib/dpkg/status` lines (no synthetic repetition).

Upstream: https://github.com/r1chardj0n3s/parse

Base commit: `cf27a9bb66f68a42a467484693b5343be8242197` (2026-11-13).
Patch: `patch.diff` — 1 file, 39 insertions, 3 deletions (`git diff --stat`).

## 本轮创新

**B 档。** 不是“随手加个 `lru_cache`”，本轮给出了三件可复算的东西：

1. **成本分解**：3000 次真实调用中 **81.6%** 的时间花在 `Parser()` 构造 +
   正则编译，匹配只占 **18.4%**（`baseline.json.cost_split`）。所以旧结论
   “`parse` 慢在正则匹配”是错的，慢在**每次调用重复构造**。
2. **语义键，而不是 format 键**：`extra_types` 是按**类型码**索引的
   （`{word:w}` 对应 `extra_types={"w": ...}`），同一个 format 配不同转换器
   必须得到不同结果。只按 format 缓存会静默返回错误值，实测 witness：
   `{"word": "ABC"}`（错误）vs `{"word": "abc"}`（正确）。本实现把
   `(format, case_sensitive, 转换器对象身份)` 一起做键；转换器不可哈希时
   **直接回退**到新建 `Parser`（运行时双路径）。
3. **未命中包络**：10,000 个互异 format 各只解析一次，优化后 **0.986x**
   （仅慢 1.4%，`benchmark/optimized.json.distinct_envelope`），证明缓存不会
   让“一次性格式”变慢。

与常见的 `@lru_cache` on `format` 方案相比：那种方案在本轮差分测试的
`extra_types` 用例上会给出错误答案；本轮实现 1,153 条逐字节一致、0 mismatch。

## 结果（真实语料）

语料：`benchmark/corpus/dpkg-status-lines.txt` —— 本机
`/var/lib/dpkg/status` 中 3,143 行真实 `Package:` / `Version:` / `Depends:`
记录（143,457 B，sha256 见 JSON），不是构造数据。每个规模 warmup 3 次、
采样 5 次，原始样本在 `benchmark/raw/`。

| 规模（行） | 基线中位数 | 优化后中位数 | 加速比 |
| --- | --- | --- | --- |
| 500 | 4.750 ms | 2.003 ms | **2.37x** |
| 1,500 | 14.140 ms | 5.736 ms | **2.47x** |
| 3,000 | 28.243 ms | 11.385 ms | **2.48x** |

三规模加速比中位数 **2.47x**；最大规模 **2.48x**。同一对树的重复跑波动
≤1.5% RSD（`scales.*.rsd`，全部 <0.02）。局限要说清：收益只发生在
**module-level `parse()` / `search()` 被重复调用**时；自己复用
`Parser` 实例的代码本来就没有这部分开销，本补丁不会让它更快。

## 质量闸门

| 闸门 | 结论 | 复现命令 |
| --- | --- | --- |
| G1 上游测试全绿 | 改动前后均 **178 passed, 1 skipped, 0 failed** | `cd <tree> && .venv/bin/python -m pytest tests -q -o addopts=""` |
| G2 差分一致 | **1,079 个 sha256 去重后的互异输入，1,153/1,153 行逐字节相同，0 mismatch** | `python3 tests/test_diff.py --baseline <upstream> --optimized <patched>` |
| G3 中位加速 | **2.47x** ≥ 1.15x | `python3 benchmark/bench.py --src <tree> --tag <t> --out benchmark --corpus benchmark/corpus/dpkg-status-lines.txt` |
| G3b 真实语料 | 真实 dpkg 记录上 **2.47x** ≥ 1.15x | 同上（语料即真实文件） |
| G4 大规模不退化 | 3,000 行 **2.48x** ≥ 0.95x；10,000 互异格式未命中路径 **0.986x** | 同上 + `distinct_envelope` |
| G5 内存不变差 | 峰值 RSS **12,672 kB → 12,672 kB = 1.000x** | `/usr/bin/time -v python3 -c "..."`（120,000 次 parse，见下） |

G5 命令（两棵树各跑一次，读 `Maximum resident set size`）：

```bash
/usr/bin/time -v python3 -c "import sys;sys.path.insert(0,'<tree>');import parse
for _ in range(120000): parse.parse('Package: {name}','Package: libc6')"
```

**解释器交叉**：本机只有 `/usr/bin/python3.12`（3.12.3），无 3.10/3.11，
因此未做跨版本交叉，也没有编造多版本数据。

## 复现（3 条命令）

```bash
git clone --depth=1 https://github.com/r1chardj0n3s/parse.git upstream && cp -a upstream patched && git -C patched apply "$PWD/patch.diff"
python3 benchmark/bench.py --src upstream --tag baseline --out benchmark --corpus benchmark/corpus/dpkg-status-lines.txt && python3 benchmark/bench.py --src patched --tag optimized --out benchmark --corpus benchmark/corpus/dpkg-status-lines.txt
python3 tests/test_diff.py --baseline upstream --optimized patched
```

## 环境

- CPU: AMD EPYC 7K62 48-Core Processor（`/proc/cpuinfo`），4 vCPU
- 内存: 3,723 MB
- 运行时: CPython 3.12.3，pytest 9.x
- 种子: `20261114`（bench 的互异格式生成与差分语料共用）
- 上游测试命令/结果已写入 `benchmark/baseline.json.upstream_tests`
  与 `benchmark/optimized.json.upstream_tests`
- 仓库不含上游源码副本；`patch.diff` 在 base commit 的干净 clone 上
  `git apply --check` 通过

## 目录

```
benchmark/bench.py                 计时、原始样本、成本分解
benchmark/baseline.json            基线聚合（含 upstream_tests/cost_split）
benchmark/optimized.json           优化后聚合
benchmark/raw/*.json               每个规模每次采样的原始样本
benchmark/corpus/                  真实 dpkg status 行语料（含来源说明）
tests/test_diff.py                 差分入口（1,153 条，去重 1,079）
tests/_probe.py                    在独立子进程中跑一棵树并输出规范 JSONL
patch.diff                         39+/3-，仅 parse/__init__.py
LICENSE                            上游 MIT 原文 + 来源/改动说明
```
