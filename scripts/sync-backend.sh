#!/usr/bin/env bash
#
# 把本地最新的 backend/ 安全同步到云端服务器并重启征稿后端。
#
# 解决「本地改了后端、线上 /opt/photo-aiid 没更新」的老问题：线上目录不是 git 仓库，
# 靠手动 scp 容易漏传、又容易把服务器自己的 .env / 数据库覆盖掉。本脚本用 rsync 同步，
# **强制排除**服务器上的密钥、数据库、虚拟环境与运行时状态，传完自动重启 photo-intake。
#
# 在本地（Mac）运行，不是在服务器上：
#   bash scripts/sync-backend.sh                 # 用下面的默认值同步并重启
#   DRY=1 bash scripts/sync-backend.sh           # 预演：只显示会传哪些文件，不实际改动
#   REMOTE=root@1.2.3.4 APP_DIR=/opt/x bash scripts/sync-backend.sh   # 覆盖目标
#
# 可用环境变量（均有默认值）：
#   REMOTE   SSH 目标       默认 root@47.236.198.127
#   APP_DIR  服务器代码根   默认 /opt/photo-aiid   （backend/ 在其下）
#   SERVICE  systemd 服务   默认 photo-intake
#   DRY=1    只预演不改动（rsync --dry-run，且跳过重启）
#
# 前置：本机能 ssh 到 REMOTE（会提示输入密码）；服务器已装 rsync。
set -euo pipefail

REMOTE="${REMOTE:-root@47.236.198.127}"
APP_DIR="${APP_DIR:-/opt/photo-aiid}"
SERVICE="${SERVICE:-photo-intake}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_BACKEND="$(cd "$SCRIPT_DIR/../backend" && pwd)"

[[ -f "$LOCAL_BACKEND/intake.py" ]] || {
  echo "✗ 没找到本地 backend/intake.py（$LOCAL_BACKEND），路径不对？" >&2; exit 1; }
command -v rsync >/dev/null 2>&1 || { echo "✗ 本机未装 rsync。" >&2; exit 1; }

# 绝不覆盖服务器上的：密钥/环境、数据库、虚拟环境、Python 缓存、运行时状态、日志。
EXCLUDES=(
  --exclude ".env"
  --exclude "*.db" --exclude "*.db-wal" --exclude "*.db-shm"
  --exclude ".venv" --exclude "__pycache__"
  --exclude "archive_state.json"      # 服务器本地的归档状态，勿覆盖
  --exclude "*.log"
  --exclude ".DS_Store"
)

RSYNC_FLAGS=(-avz --delete-after --itemize-changes)
ACTION="同步并重启"
if [[ "${DRY:-}" == "1" ]]; then
  RSYNC_FLAGS+=(--dry-run)
  ACTION="预演（不改动）"
fi

echo "==> $ACTION"
echo "    本地: $LOCAL_BACKEND/"
echo "    远端: $REMOTE:$APP_DIR/backend/"
echo "    排除: .env / *.db / .venv / __pycache__ / archive_state.json / *.log"
echo

# 注意结尾的斜杠：把 backend/ 的内容同步进远端 backend/ 内。--delete-after 让远端与本地
# 一致（排除项不受影响），从而清掉线上残留的过时文件。
rsync "${RSYNC_FLAGS[@]}" "${EXCLUDES[@]}" \
  "$LOCAL_BACKEND/" "$REMOTE:$APP_DIR/backend/"

if [[ "${DRY:-}" == "1" ]]; then
  echo
  echo "✓ 预演完成。以上为将要传输/删除的文件。去掉 DRY=1 即真正执行。"
  exit 0
fi

echo
echo "==> 重启 $SERVICE 并校验"
ssh "$REMOTE" "systemctl restart '$SERVICE' && sleep 2 && systemctl is-active '$SERVICE'"

echo
echo "✓ 后端已同步并重启。若刚改了状态/接口，回 App 重新打开面板即可看到最新状态。"
