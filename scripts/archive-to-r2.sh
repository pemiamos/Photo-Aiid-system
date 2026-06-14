#!/usr/bin/env bash
#
# 把一本书的征稿原图从阿里云 OSS 搬到 Cloudflare R2 长期归档。
# 流程：导出元数据 → copy → check 核对 → （可选）核对通过后清空 OSS。
#
# 前置：
#   1. 安装 rclone：https://rclone.org/downloads/
#   2. 配好 ~/.config/rclone/rclone.conf（参考 scripts/rclone.conf.example，
#      remote 名须为 oss 与 r2）
#
# 用法：
#   scripts/archive-to-r2.sh <书目代号> [--purge]
#   例： scripts/archive-to-r2.sh 2026-sanxia
#        scripts/archive-to-r2.sh 2026-sanxia --purge   # 核对通过后清空 OSS
#
# 可用环境变量覆盖默认：
#   OSS_BUCKET (默认 photo-intake)  R2_BUCKET (默认 photo-archive)
#   PHOTO_AIID_DB (默认 backend/photo_aiid.db)

set -euo pipefail

BOOK="${1:-}"
PURGE="${2:-}"
if [[ -z "$BOOK" ]]; then
  echo "用法: $0 <书目代号> [--purge]" >&2
  exit 1
fi

OSS_BUCKET="${OSS_BUCKET:-photo-intake}"
R2_BUCKET="${R2_BUCKET:-photo-archive}"
PHOTO_AIID_DB="${PHOTO_AIID_DB:-backend/photo_aiid.db}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

SRC="oss:${OSS_BUCKET}/${BOOK}"
DST="r2:${R2_BUCKET}/${BOOK}"

echo "▶ 归档书目：${BOOK}"
echo "  源 ${SRC}"
echo "  目标 ${DST}"

# 0) 导出投稿/授权元数据并上传到 OSS 的 {书}/_meta/，与原图一起归档
if [[ -f "$PHOTO_AIID_DB" ]]; then
  echo "▶ [0/3] 导出投稿/授权记录 → _meta/submissions.csv"
  TMP_CSV="$(mktemp -t submissions.XXXXXX.csv)"
  python3 "${SCRIPT_DIR}/export-intake-meta.py" --book "$BOOK" --db "$PHOTO_AIID_DB" --out "$TMP_CSV"
  rclone copyto "$TMP_CSV" "${SRC}/_meta/submissions.csv"
  rm -f "$TMP_CSV"
else
  echo "  （跳过元数据导出：未找到 $PHOTO_AIID_DB）"
fi

# 1) 搬运（带校验、断点续传、4 并发）
echo "▶ [1/3] rclone copy"
rclone copy "$SRC" "$DST" --transfers 4 --checksum --progress

# 2) 核对两边一致（必须通过才允许清理）
echo "▶ [2/3] rclone check 核对"
if rclone check "$SRC" "$DST" --checksum; then
  echo "  ✓ 核对一致"
else
  echo "  ✗ 核对不一致，已中止，不会清理 OSS" >&2
  exit 2
fi

# 3) 可选：核对通过后清空 OSS 该书前缀，省存储费
if [[ "$PURGE" == "--purge" ]]; then
  read -r -p "核对已通过。确认清空 OSS 中 ${SRC} ？输入 yes 继续: " ans
  if [[ "$ans" == "yes" ]]; then
    echo "▶ [3/3] 清空 OSS ${SRC}"
    rclone delete "$SRC"
    rclone rmdirs "$SRC" --leave-root || true
    echo "  ✓ 已清空 OSS（归档保留在 R2）"
  else
    echo "  已取消清理，OSS 原样保留"
  fi
else
  echo "▶ [3/3] 未加 --purge，OSS 原样保留（确认无误后可再跑加 --purge）"
fi

echo "✓ 完成"
