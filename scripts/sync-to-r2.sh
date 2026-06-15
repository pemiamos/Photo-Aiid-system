#!/usr/bin/env bash
#
# 持续把征稿原图从阿里云 OSS 镜像到 Cloudflare R2（只增不删，可定时反复跑）。
# 与 archive-to-r2.sh 的区别：本脚本面向「征稿期间持续同步」——
#   - 永不删 OSS（OSS 是长期主存，R2 是异地备份镜像）
#   - 带文件锁，定时任务重叠时自动跳过，不会并发跑崩
#   - 只做 copy（增量、跳过已同步文件），核对可选
#
# 前置：rclone 已装、~/.config/rclone/rclone.conf 配好 remote「oss」与「r2」。
#
# 用法：
#   scripts/sync-to-r2.sh <书目代号> [--check]
#   例： scripts/sync-to-r2.sh 2026-sanxia            # 仅增量同步
#        scripts/sync-to-r2.sh 2026-sanxia --check     # 同步后顺带核对一致性
#
# 定时（每 10 分钟，macOS/Linux 通用 crontab 写法）：
#   */10 * * * * /bin/bash /绝对路径/scripts/sync-to-r2.sh 2026-sanxia >> /tmp/sync-r2.log 2>&1
#
# 可用环境变量覆盖默认：OSS_BUCKET(默认 photo-intake) R2_BUCKET(默认 photo-archive)

set -euo pipefail

BOOK="${1:-}"
CHECK="${2:-}"
if [[ -z "$BOOK" ]]; then
  echo "用法: $0 <书目代号> [--check]" >&2
  exit 1
fi

OSS_BUCKET="${OSS_BUCKET:-photo-intake}"
R2_BUCKET="${R2_BUCKET:-photo-archive}"
SRC="oss:${OSS_BUCKET}/${BOOK}"
DST="r2:${R2_BUCKET}/${BOOK}"

# 跨平台原子锁（mkdir 在所有平台都原子）：同书目同步串行，重叠则本次跳过。
# 退出时清理锁；陈旧锁（进程已死）也能自动接管。
LOCK="/tmp/sync-to-r2-${BOOK}.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  if [[ -f "$LOCK/pid" ]] && kill -0 "$(cat "$LOCK/pid")" 2>/dev/null; then
    echo "$(date '+%F %T') 上一次 ${BOOK} 同步还在跑，跳过本次。"
    exit 0
  fi
  # 锁存在但持有进程已死 → 接管
  rm -rf "$LOCK"; mkdir "$LOCK"
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

echo "$(date '+%F %T') ▶ 同步 ${SRC} → ${DST}"
# 增量 copy：只传新增/变化文件，已同步的按 size+checksum 跳过；永不删目标
rclone copy "$SRC" "$DST" --transfers 4 --checksum
echo "$(date '+%F %T') ✓ 同步完成"

if [[ "$CHECK" == "--check" ]]; then
  echo "$(date '+%F %T') ▶ 核对一致性"
  if rclone check "$SRC" "$DST" --checksum; then
    echo "$(date '+%F %T') ✓ 核对一致"
  else
    echo "$(date '+%F %T') ✗ 核对不一致（不影响 OSS，下次同步会补齐）" >&2
  fi
fi
