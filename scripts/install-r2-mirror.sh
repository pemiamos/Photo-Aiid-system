#!/usr/bin/env bash
#
# 安装「OSS→R2 持续镜像」的 systemd service + timer（默认每 5 分钟一轮）。幂等。
# 在服务器上 sudo 运行；前置：已跑过 scripts/setup-rclone.sh（装好并配好 rclone）。
#
# 用法：
#   sudo bash scripts/install-r2-mirror.sh [代码目录] [间隔]
#   例： sudo bash scripts/install-r2-mirror.sh /opt/photo-aiid 15min
set -euo pipefail

APP_DIR="${1:-/opt/photo-aiid}"
INTERVAL="${2:-15min}"
INTAKE_SVC="photo-intake"

[[ $EUID -eq 0 ]] || { echo "请用 sudo 运行。" >&2; exit 1; }
SCRIPTS_DIR="$APP_DIR/scripts"
[[ -f "$SCRIPTS_DIR/mirror-oss-to-r2.sh" ]] || {
  echo "缺 $SCRIPTS_DIR/mirror-oss-to-r2.sh，请先把仓库 scripts/ 同步到服务器。" >&2; exit 1; }
command -v rclone >/dev/null 2>&1 || {
  echo "未检测到 rclone，请先跑 scripts/setup-rclone.sh 配好 rclone。" >&2; exit 1; }

# 跟征稿后端用同一个运行用户（才能读到它家目录里的 rclone.conf）
RUN_USER="$(systemctl show "$INTAKE_SVC" -p User --value 2>/dev/null || true)"
[[ -n "$RUN_USER" ]] || RUN_USER="root"

# 读 .env 桶名（缺省兜底）
ENV_FILE="$APP_DIR/.env"; [[ -f "$ENV_FILE" ]] || ENV_FILE="$(dirname "$APP_DIR")/.env"
getv() { [[ -f "$ENV_FILE" ]] && grep -E "^$1=" "$ENV_FILE" | head -n1 | cut -d= -f2- | tr -d '"'\''' | tr -d '\r' || true; }
OSS_BUCKET="$(getv OSS_BUCKET)"; : "${OSS_BUCKET:=photo-intake}"
R2_BUCKET="${R2_BUCKET:-photo-archive}"

echo "==> 运行用户 $RUN_USER；镜像 oss:$OSS_BUCKET → r2:$R2_BUCKET；间隔 $INTERVAL"

cat > /etc/systemd/system/photo-r2-mirror.service <<EOF
[Unit]
Description=Photo-Aiid OSS→R2 持续镜像（增量备份，永不删除）
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$RUN_USER
WorkingDirectory=$APP_DIR
Environment=OSS_BUCKET=$OSS_BUCKET R2_BUCKET=$R2_BUCKET
ExecStart=/usr/bin/env bash $SCRIPTS_DIR/mirror-oss-to-r2.sh
EOF

cat > /etc/systemd/system/photo-r2-mirror.timer <<EOF
[Unit]
Description=每 $INTERVAL 触发一次 OSS→R2 镜像

[Timer]
OnBootSec=2min
OnUnitActiveSec=$INTERVAL
Persistent=true

[Install]
WantedBy=timers.target
EOF

touch /var/log/photo-r2-mirror.log /var/log/photo-r2-mirror.state
chown "$RUN_USER":"$(id -gn "$RUN_USER")" /var/log/photo-r2-mirror.log /var/log/photo-r2-mirror.state

systemctl daemon-reload
systemctl enable --now photo-r2-mirror.timer
systemctl start --no-block photo-r2-mirror.service   # 立即触发首轮（后台跑，不阻塞）

echo
echo "✓ 已启用 photo-r2-mirror.timer（每 $INTERVAL 一轮），并已触发首轮全量镜像。"
echo "  看进度： tail -f /var/log/photo-r2-mirror.log"
echo "  看计划： systemctl list-timers photo-r2-mirror.timer"
echo "  停掉：   sudo systemctl disable --now photo-r2-mirror.timer"
