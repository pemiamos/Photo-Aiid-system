#!/usr/bin/env python3
"""下载本地视觉预分类所需模型到 backend/models/（约 148MB，不入 git）。

用法:
    python scripts/download-fast-models.py                 # 默认走 hf-mirror.com
    python scripts/download-fast-models.py --source hf     # 走 huggingface.co
    python scripts/download-fast-models.py --check         # 只检查现有文件

设计要点:
  * 只用标准库（urllib），不引入额外下载依赖
  * 断点续传：HF 在中国大陆经常断在 80%，重跑会从断点继续而不是从头
  * 大小校验：下完比对 Content-Length，避免半截文件被当成成功
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "backend" / "models"

# (远端路径, 本地文件名, 期望字节数, 所属 repo)
FILES = [
    ("Xenova/clip-vit-base-patch32", "onnx/vision_model_quantized.onnx",
     "vision_model_quantized.onnx", 89_128_971),
    ("Xenova/clip-vit-base-patch32", "onnx/text_model_quantized.onnx",
     "text_model_quantized.onnx", 64_507_187),
    ("Xenova/clip-vit-base-patch32", "tokenizer.json",
     "tokenizer.json", 2_224_119),
    ("opencv/face_detection_yunet", "face_detection_yunet_2023mar.onnx",
     "face_detection_yunet.onnx", 232_589),
]

SOURCES = {
    "mirror": "https://hf-mirror.com",
    "hf": "https://huggingface.co",
}


def url_for(base: str, repo: str, remote: str) -> str:
    return f"{base}/{repo}/resolve/main/{remote}"


def human(n: int) -> str:
    return f"{n / 1e6:.1f}MB" if n >= 1e6 else f"{n / 1e3:.0f}KB"


def download(base: str, repo: str, remote: str, dst: Path, expect: int,
             retries: int = 12) -> bool:
    """带断点续传的下载。网络断在任意位置都能接着下。"""
    url = url_for(base, repo, remote)
    for attempt in range(1, retries + 1):
        have = dst.stat().st_size if dst.exists() else 0
        if have >= expect * 0.995:
            print(f"  ✓ {dst.name}  {human(have)}  (已完整)")
            return True
        req = urllib.request.Request(url)
        if have:
            req.add_header("Range", f"bytes={have}-")
            print(f"  ↻ {dst.name}  从 {human(have)} 续传 (第 {attempt} 次)")
        else:
            print(f"  ↓ {dst.name}  {attempt}/{retries}")

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                total = expect
                cr = resp.headers.get("Content-Length")
                if cr and not have:
                    total = int(cr)
                mode = "ab" if have else "wb"
                got = have
                last = 0.0
                with open(dst, mode) as f:
                    while True:
                        chunk = resp.read(1 << 20)      # 1MB
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        if time.time() - last > 2:
                            last = time.time()
                            pct = got / max(total, 1) * 100
                            sys.stdout.write(f"\r      {human(got)} / {human(total)}  {pct:5.1f}%")
                            sys.stdout.flush()
                print()
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            print(f"\n      ⚠ 中断: {type(e).__name__}: {str(e)[:110]}")
            time.sleep(2)
            continue

        if dst.exists() and dst.stat().st_size >= expect * 0.995:
            print(f"  ✓ {dst.name}  {human(dst.stat().st_size)}")
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=list(SOURCES), default="mirror",
                    help="mirror=hf-mirror.com（默认，国内快）| hf=官方")
    ap.add_argument("--check", action="store_true", help="只检查不下载")
    a = ap.parse_args()
    base = SOURCES[a.source]

    MODELS.mkdir(parents=True, exist_ok=True)
    print(f"目标目录: {MODELS}")
    print(f"下载源:   {base}\n")

    missing = []
    for repo, remote, name, expect in FILES:
        dst = MODELS / name
        ok = dst.exists() and dst.stat().st_size >= expect * 0.995
        if a.check:
            mark = "✓" if ok else "✗"
            size = human(dst.stat().st_size) if dst.exists() else "缺失"
            print(f"  {mark} {name:<34} {size:>10}  期望 {human(expect)}")
            if not ok:
                missing.append(name)
            continue
        if ok:
            print(f"  ✓ {name}  {human(dst.stat().st_size)}  (已存在)")
            continue
        if not download(base, repo, remote, dst, expect):
            missing.append(name)

    if a.check:
        print(f"\n{'全部就绪' if not missing else '缺 ' + str(len(missing)) + ' 个文件'}")
        return 0 if not missing else 1

    if missing:
        print(f"\n✗ 以下文件下载失败，请重跑本脚本（会断点续传）:")
        for m in missing:
            print(f"   - {m}")
        return 1

    total = sum((MODELS / n).stat().st_size for _, _, n, _ in FILES)
    print(f"\n✓ 全部就绪，共 {human(total)}")
    print(f"  启动后在浏览器打开 http://localhost:8000/fast")
    return 0


if __name__ == "__main__":
    sys.exit(main())
