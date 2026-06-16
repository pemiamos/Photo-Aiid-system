#!/usr/bin/env bash
#
# OSS → R2 增量镜像（持续备份）。供 systemd timer 周期调用。
# 只「复制新文件」，**永不删除**两边任何东西；投稿文件名唯一、内容不变，
# 故用 --size-only 判定，已备份的不会重复传。
#
# 依赖：本机已装 rclone 且配好 remote `oss` 与 `r2`（见 scripts/setup-rclone.sh）。
#
# 环境变量（可选）：
#   OSS_BUCKET (默认 photo-intake)  R2_BUCKET (默认 photo-archive)
#   R2_MIRROR_LOG (默认 /var/log/photo-r2-mirror.log)
#   R2_MIRROR_STATE (默认 /var/log/photo-r2-mirror.state) —— 供后端读，反映上轮成败
set -uo pipefail   # 不用 -e：要自己捕获 rclone 成败并落状态

OSS_BUCKET="${OSS_BUCKET:-photo-intake}"
R2_BUCKET="${R2_BUCKET:-photo-archive}"
LOG="${R2_MIRROR_LOG:-/var/log/photo-r2-mirror.log}"
STATE="${R2_MIRROR_STATE:-/var/log/photo-r2-mirror.state}"
LOCK="/tmp/photo-r2-mirror.lock"

# 写状态 JSON：$1=true/false  $2=消息
write_state() {
  printf '{"at":"%s","ok":%s,"msg":"%s"}\n' \
    "$(date '+%F %T')" "$1" "$(printf '%s' "$2" | tr -d '"\\' | head -c 200)" > "$STATE" 2>/dev/null || true
}

# 防重叠：上一轮没跑完就跳过本轮
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(date '+%F %T') 上一轮镜像仍在进行，跳过本轮" >> "$LOG"
  exit 0
fi

echo "$(date '+%F %T') ▶ 镜像 oss:$OSS_BUCKET → r2:$R2_BUCKET" >> "$LOG"
if rclone copy "oss:$OSS_BUCKET" "r2:$R2_BUCKET" \
     --size-only --transfers 4 --fast-list \
     --log-file "$LOG" --log-level INFO --stats 0; then
  echo "$(date '+%F %T') ✓ 本轮镜像完成" >> "$LOG"
  write_state true ""
else
  rc=$?
  # 取日志里最后一条 ERROR/Failed 作为简要原因
  reason="$(grep -iE 'error|failed' "$LOG" 2>/dev/null | tail -n1 | head -c 200)"
  [ -n "$reason" ] || reason="rclone 退出码 $rc"
  echo "$(date '+%F %T') ✗ 本轮镜像失败（退出码 $rc）" >> "$LOG"
  write_state false "$reason"
  exit "$rc"
fi
