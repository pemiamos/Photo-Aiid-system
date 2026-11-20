#!/usr/bin/env python3
"""本地视觉预分类的基准测试（可复现文档里的 87% / 85%）。

用法:
    # 1) 只看分类结果（人工核对）
    python scripts/bench-fast-classify.py D:/pics --limit 30

    # 2) 有标注时算准确率。labels.csv 两列：文件名,正确类别
    python scripts/bench-fast-classify.py D:/pics --limit 30 --labels labels.csv

    # 3) 测中文检索与英文基准的 top-10 重合率
    python scripts/bench-fast-classify.py D:/pics --bench-search

说明:
  * 不写库、不改索引，纯读图跑一遍，用于验证精度与耗时
  * 分类准确率的分母是「有标注的行数」，不是图片总数
  * 检索重合率 = 中文查询扩展后 top-10 与人工英译 top-10 的交集比例，
    **它衡量的是"中文查询能不能复现英文查询的结果"，不等于检索相关性准确率**
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from services.fastvec import FastVec, IMG_EXT  # noqa: E402
from services import zh_lexicon  # noqa: E402


def collect(root: str, limit: int | None) -> list[str]:
    out = []
    for dirpath, dirnames, files in __import__("os").walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for f in files:
            if not f.startswith(".") and Path(f).suffix.lower() in IMG_EXT:
                out.append(str(Path(dirpath) / f))
    out.sort()
    return out[:limit] if limit else out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--labels", default=None, help="CSV: 文件名,正确类别")
    ap.add_argument("--bench-search", action="store_true")
    a = ap.parse_args()

    paths = collect(a.root, a.limit)
    if not paths:
        print("没有找到图片")
        return 1
    print(f"图片 {len(paths)} 张  batch={a.batch}\n")

    fv = FastVec(db_path=str(Path(__file__).parent / ".bench.db"))
    ok, why = True, ""
    try:
        fv.load()
    except Exception as e:
        ok, why = False, f"{type(e).__name__}: {e}"
    if not ok:
        print(f"模型加载失败: {why}")
        print("先跑: python scripts/download-fast-models.py")
        return 1
    print(f"模型加载 {fv.load_ms:.0f}ms  推理后端=onnxruntime CPUExecutionProvider\n")

    t0 = time.time()
    items, vecs = fv.analyze_batch(paths, batch=a.batch)
    dt = time.time() - t0
    good = [it for it in items if not it.error]
    print(f"编码 {dt:.1f}s  ({dt/len(paths)*1000:.0f} ms/张)  "
          f"成功 {len(good)}  失败 {len(items)-len(good)}")
    print(f"外推: 1万张 {dt/len(paths)*10000/60:.0f} 分钟\n")

    labels = {}
    if a.labels:
        with open(a.labels, encoding="utf-8-sig") as f:
            for row in csv.reader(f):
                if len(row) >= 2:
                    labels[row[0].strip()] = row[1].strip()

    hit = miss = 0
    print(f"  {'文件':<40} {'top1':<10} {'置信':>6}  {'top2':<10} {'top3':<10}")
    for it in items:
        name = Path(it.path).name
        if it.error:
            print(f"  {name[:38]:<40} [解码失败] {it.error[:30]}")
            continue
        t = it.top
        mark = ""
        if name in labels:
            if labels[name] == it.category:
                hit += 1; mark = " ✓"
            else:
                miss += 1; mark = f" ✗(应 {labels[name]})"
        print(f"  {name[:38]:<40} {it.category:<10} {it.conf:>6.3f}  "
              f"{t[1]['cls'] if len(t)>1 else '':<10} {t[2]['cls'] if len(t)>2 else '':<10}{mark}")

    if labels:
        n = hit + miss
        print(f"\n  分类 top-1 准确率: {hit}/{n} = {hit/max(n,1)*100:.1f}%  （分母是有标注的 {n} 张）")
    else:
        print("\n  未提供 --labels，跳过准确率计算")

    low = sum(1 for it in good if it.low_conf)
    print(f"  低置信(<0.5): {low}/{len(good)} = {low/max(len(good),1)*100:.0f}%  ← 送 LLM 的比例")

    if a.bench_search:
        print("\n  中文检索 vs 英文基准（top-10 重合率）")
        fv.store(good, vecs[[i for i, it in enumerate(items) if not it.error]])
        pairs = [
            ("猫", "a photo of a cat"), ("中式古建筑", "chinese temple architecture"),
            ("日落", "sunset"), ("缆车", "cable car"),
            ("水下礁石", "underwater rock"), ("江边风景", "riverside landscape"),
        ]
        rates = []
        for zh, en in pairs:
            auto, _, ratio = zh_lexicon.expand(zh)
            used = auto or zh
            a_top = {p for p, _ in fv.search(used, 10)}
            b_top = {p for p, _ in fv.search(en, 10)}
            r = len(a_top & b_top) / 10
            rates.append(r)
            print(f"    「{zh}」→ {used:<28} 重合 {r*100:3.0f}%")
        print(f"    平均 {sum(rates)/len(rates)*100:.0f}%（仅供参考，非相关性准确率）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
