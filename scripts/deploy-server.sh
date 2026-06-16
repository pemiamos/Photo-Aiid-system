#!/usr/bin/env bash
#
# 把「征稿云端精简后端」部署到一台干净的 Ubuntu 服务器（阿里云轻量/ECS 或任意 Linux）。
# 幂等：可重复运行。完成后摄影师访问 https://<域名>/intake 即可投稿。
#
# 用法（在服务器上，sudo 运行）：
#   sudo bash scripts/deploy-server.sh <域名> [代码目录]
#   例： sudo bash scripts/deploy-server.sh intake.example.com /opt/photo-intake
#
# 不带域名（仅用公网 IP + HTTP 临时测试，不签证书）：
#   sudo bash scripts/deploy-server.sh - /opt/photo-intake
#
# 前置：
#   1. 已把仓库的 backend/ 目录上传到 <代码目录>（含 intake_server.py、intake.py、
#      database.py、intake_page.html、requirements-server.txt）。
#   2. <代码目录>/.env 已填好 OSS_* 五项 + INTAKE_ADMIN_TOKEN（见 docs/部署到阿里云.md）。
#   3. 域名已解析到本机公网 IP，安全组放行 22/80/443。
set -euo pipefail

DOMAIN="${1:-}"
APP_DIR="${2:-/opt/photo-intake}"
SERVICE_NAME="photo-intake"
PY_BIN="python3"

if [[ -z "$DOMAIN" ]]; then
  echo "用法: sudo bash scripts/deploy-server.sh <域名|-> [代码目录]" >&2
  exit 1
fi
if [[ $EUID -ne 0 ]]; then
  echo "请用 sudo 运行。" >&2
  exit 1
fi

APP_DIR="$(cd "$APP_DIR" && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$SCRIPT_DIR/../deploy" && pwd)"

echo "==> 检查代码目录：$APP_DIR"
for f in intake_server.py intake.py database.py intake_page.html requirements-server.txt; do
  [[ -f "$APP_DIR/$f" ]] || { echo "缺少 $APP_DIR/$f，请先上传 backend/ 全部文件。" >&2; exit 1; }
done
if [[ ! -f "$APP_DIR/.env" && ! -f "$(dirname "$APP_DIR")/.env" ]]; then
  echo "警告：未找到 .env（$APP_DIR/.env 或其上级目录），后台将无鉴权且无 OSS。建议先按教程填好再部署。" >&2
fi

echo "==> 安装系统依赖（python venv / nginx / certbot）"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
# 版本专用的 venv 包（如 python3.10-venv）才保证 venv 自带 pip，python3-venv 元包不总能拉全
PYVER="$("$PY_BIN" -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
apt-get install -y python3-venv "python${PYVER}-venv" python3-pip nginx
if [[ "$DOMAIN" != "-" ]]; then
  apt-get install -y certbot python3-certbot-nginx
fi

echo "==> 建虚拟环境并安装精简依赖"
if [[ ! -x "$APP_DIR/.venv/bin/pip" ]]; then
  rm -rf "$APP_DIR/.venv"
  "$PY_BIN" -m venv "$APP_DIR/.venv"
  # 兜底：若 venv 仍未带 pip，用 ensurepip 引导
  "$APP_DIR/.venv/bin/python" -m ensurepip --upgrade 2>/dev/null || true
fi
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements-server.txt"

echo "==> 写 systemd 服务：$SERVICE_NAME"
sed "s#__APP_DIR__#$APP_DIR#g" "$DEPLOY_DIR/photo-intake.service" \
  > "/etc/systemd/system/$SERVICE_NAME.service"
# 让服务以调用 sudo 的普通用户身份运行（数据库/上传文件归属正常）
RUN_USER="${SUDO_USER:-root}"
if ! grep -q "^User=" "/etc/systemd/system/$SERVICE_NAME.service"; then
  sed -i "/^\[Service\]/a User=$RUN_USER" "/etc/systemd/system/$SERVICE_NAME.service"
fi
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo "==> 写 nginx 反代"
if [[ "$DOMAIN" == "-" ]]; then
  SRV_NAME="_"
else
  SRV_NAME="$DOMAIN"
fi
sed "s#__DOMAIN__#$SRV_NAME#g" "$DEPLOY_DIR/nginx-intake.conf" \
  > "/etc/nginx/sites-available/$SERVICE_NAME.conf"
ln -sf "/etc/nginx/sites-available/$SERVICE_NAME.conf" \
  "/etc/nginx/sites-enabled/$SERVICE_NAME.conf"
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

if [[ "$DOMAIN" != "-" ]]; then
  echo "==> 申请 HTTPS 证书（Let's Encrypt）"
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
    --register-unsafely-without-email --redirect || {
      echo "证书申请失败：请确认域名已解析到本机、80 端口可达、（大陆节点）已备案。" >&2
      echo "后端已在运行，可先用 http://$DOMAIN 测试。" >&2
    }
fi

echo
echo "================ 部署完成 ================"
systemctl --no-pager --full status "$SERVICE_NAME" | head -n 5 || true
echo
if [[ "$DOMAIN" == "-" ]]; then
  IP="$(curl -s https://api.ipify.org || echo '<你的公网IP>')"
  echo "投稿页（HTTP 临时）: http://$IP/intake"
  echo "App 征稿服务器地址 : http://$IP"
else
  echo "投稿页: https://$DOMAIN/intake"
  echo "App 征稿服务器地址: https://$DOMAIN"
fi
echo "健康检查: curl -s http://127.0.0.1:8000/healthz"
echo "查看日志: journalctl -u $SERVICE_NAME -f"
echo "改完 .env 后重启: sudo systemctl restart $SERVICE_NAME"
