#!/usr/bin/env python3
"""下载本地视觉预分类所需模型到 backend/models/（约 148MB，不入 git）。

用法:
    python scripts/download-fast-models.py                 # 默认走 hf-mirror.com
    python scripts/download-fast-models.py --source hf     # 走 huggingface.co
    python scripts/download-fast-models.py --check         # 只校验不下载
    python scripts/download-fast-models.py --force         # 忽略现有文件重下

设计要点:
  * 只用标准库（urllib），不引入额外下载依赖
  * 断点续传：HF 在中国大陆经常断在 80%，重跑会从断点继续
  * **精确校验**：比对官方字节数 + sha256（大小与哈希都取自 HF API，
    不是估算值）。以前用 `>= size*0.995` 会把截断文件判成完整。
  * **检查 206**：续传时必须确认服务器返回 206 Partial Content；
    若返回 200（服务器忽略 Range，回了全量），必须清空重下，
    否则会把全量内容追加到已有字节后面，拼出一个大小正确但内容损坏的文件。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "backend" / "models"

# (repo, 远端路径, 本地文件名, 精确字节数, sha256)
# 数字与哈希取自 HF API（/api/models/{repo}/tree/main），不是估算。
# sha256 为 None 表示该文件不是 LFS 对象，只校验字节数。
FILES = [
    ("Xenova/clip-vit-base-patch32", "onnx/vision_model_quantized.onnx",
     "vision_model_quantized.onnx", 89_117_001,
     "583fd1110a514667812fee7d684952aaf82a99b959760c8d7dca7e0ab9839299"),
    ("Xenova/clip-vit-base-patch32", "onnx/text_model_quantized.onnx",
     "text_model_quantized.onnx", 64_504_507,
     "73baab855d406190da9faa498cfedf65f15cf309f4cc7385b7b032e6d08e5c3a"),
    ("Xenova/clip-vit-base-patch32", "tokenizer.json",
     "tokenizer.json", 2_224_119, None),
    ("opencv/face_detection_yunet", "face_detection_yunet_2023mar.onnx",
     "face_detection_yunet.onnx", 232_589,
     "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"),
]

SOURCES = {
    "mirror": "https://hf-mirror.com",
    "hf": "https://huggingface.co",
}


def url_for(base: str, repo: str, remote: str) -> str:
    return f"{base}/{repo}/resolve/main/{remote}"


def human(n: int) -> str:
    return f"{n / 1e6:.1f}MB" if n >= 1e6 else f"{n / 1e3:.0f}KB"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(path: Path, size: int, digest: str | None) -> tuple[bool, str]:
    """精确校验：字节数必须相等，且（若给出）sha256 必须匹配。"""
    if not path.exists():
        return False, "缺失"
    actual = path.stat().st_size
    if actual != size:
        return False, f"大小不符（{actual:,} ≠ {size:,}）"
    if digest:
        got = sha256_of(path)
        if got != digest:
            return False, f"sha256 不符（{got[:12]}… ≠ {digest[:12]}…）"
    return True, ""


def download(base: str, repo: str, remote: str, dst: Path, size: int,
             digest: str | None, retries: int = 12) -> bool:
    """带断点续传 + 范围校验的下载。"""
    url = url_for(base, repo, remote)
    for attempt in range(1, retries + 1):
        have = dst.stat().st_size if dst.exists() else 0
        if have > size:
            # 比预期还大：上次续传追加坏了，清掉重来
            print(f"  ! {dst.name} 比预期大 {have - size} 字节，清空重下")
            dst.unlink()
            have = 0

        req = urllib.request.Request(url)
        if have:
            req.add_header("Range", f"bytes={have}-")

        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                code = resp.status
                cr = resp.headers.get("Content-Range") or ""
                total = size
                if have and code == 206:
                    # 正常续传：Content-Range 形如 bytes 1000-999999/2000000
                    if cr:
                        try:
                            total = int(cr.rsplit("/", 1)[1])
                        except ValueError:
                            pass
                    mode = "ab"
                    print(f"  ↻ {dst.name}  续传自 {human(have)}（206, 共 {human(total)}）")
                elif have and code == 200:
                    # 服务器忽略 Range 回了全量 —— 必须覆盖写，不能追加
                    print(f"  ! {dst.name}  服务器未支持 Range（200），清空重下")
                    have = 0
                    mode = "wb"
                else:
                    mode = "wb"
                    print(f"  ↓ {dst.name}  {human(size)}  (第 {attempt}/{retries} 次)")

                got = have
                last = 0.0
                with open(dst, mode) as f:
                    while True:
                        chunk = resp.read(1 << 20)
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

        ok, why = verify(dst, size, digest)
        if ok:
            print(f"  ✓ {dst.name}  {human(size)}  校验通过")
            return True
        print(f"  ✗ {dst.name}  {why}，重试")
        if dst.exists() and dst.stat().st_size > size:
            dst.unlink()
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=list(SOURCES), default="mirror",
                    help="mirror=hf-mirror.com（默认，国内快）| hf=官方")
    ap.add_argument("--check", action="store_true", help="只校验不下载")
    ap.add_argument("--force", action="store_true", help="忽略现有文件重新下载")
    a = ap.parse_args()
    base = SOURCES[a.source]

    MODELS.mkdir(parents=True, exist_ok=True)
    print(f"目标目录: {MODELS}")
    print(f"下载源:   {base}")
    print("校验方式: 精确字节数 + sha256（取自 HF API）\n")

    missing = []
    for repo, remote, name, size, digest in FILES:
        dst = MODELS / name
        ok, why = verify(dst, size, digest)
        if a.check:
            print(f"  {'✓' if ok else '✗'} {name:<34} "
                  f"{(human(dst.stat().st_size) if dst.exists() else '缺失'):>10}"
                  f"{'' if ok else '   ' + why}")
            if not ok:
                missing.append(name)
            continue
        if ok and not a.force:
            print(f"  ✓ {name}  {human(size)}  (已存在，校验通过)")
            continue
        if dst.exists() and (a.force or why):
            if why:
                print(f"  ! {name} {why}，重新下载")
            dst.unlink(missing_ok=True)
        if not download(base, repo, remote, dst, size, digest):
            missing.append(name)

    if a.check:
        print(f"\n{'全部就绪' if not missing else f'缺/损坏 {len(missing)} 个文件'}")
        return 0 if not missing else 1

    if missing:
        print(f"\n✗ 以下文件失败，请重跑本脚本（会断点续传）:")
        for m in missing:
            print(f"   - {m}")
        return 1

    total = sum((MODELS / n).stat().st_size for _, _, n, _, _ in FILES)
    print(f"\n✓ 全部就绪，共 {human(total)}")
    print("  启动后在浏览器打开 http://localhost:8000/fast")
    return 0


if __name__ == "__main__":
    sys.exit(main())
