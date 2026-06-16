#!/usr/bin/env bash
#
# 在「运行征稿后端的服务器」上一键装好并配置 rclone，让 App 的「R2 一键归档」可用。
# 幂等：可重复运行。完成后 /api/intake/admin/archive/status 的 rclone 会变 true。
#
# 它会：
#   1. 没装 rclone 就用官方脚本装；
#   2. 从后端 .env 读 OSS 凭据（OSS_ACCESS_KEY_ID/SECRET/REGION/BUCKET）自动配 [oss] remote；
#   3. 用传入的 R2 凭据配 [r2] remote；
#   4. 写到「运行后端的那个用户」的 ~/.config/rclone/rclone.conf（权限 600）；
#   5. 自检两个 remote 能否列桶；
#   6. 重启 photo-intake 让后端重新探测 rclone。
#
# 用法（在服务器上 sudo 运行）：
#   sudo R2_ACCESS_KEY_ID=xxx R2_SECRET_ACCESS_KEY=yyy R2_ACCOUNT_ID=zzz \
#     bash scripts/setup-rclone.sh [代码目录] [运行后端的用户]
#
#   - 代码目录默认 /opt/photo-aiid（其中应有 .env、scripts/、backend/）
#   - 运行后端的用户默认取 systemd 服务 photo-intake 的 User=（探测不到则用 root）
#   - R2_ACCOUNT_ID 即 Cloudflare 账号 ID（endpoint 用它拼）
set -euo pipefail

APP_DIR="${1:-/opt/photo-aiid}"
SERVICE_NAME="photo-intake"

if [[ $EUID -ne 0 ]]; then
  echo "请用 sudo 运行。" >&2; exit 1
fi

: "${R2_ACCESS_KEY_ID:?需要环境变量 R2_ACCESS_KEY_ID（Cloudflare R2 API Token 的 Access Key ID）}"
: "${R2_SECRET_ACCESS_KEY:?需要环境变量 R2_SECRET_ACCESS_KEY（R2 API Token 的 Secret Access Key）}"
: "${R2_ACCOUNT_ID:?需要环境变量 R2_ACCOUNT_ID（Cloudflare 账号 ID）}"

ENV_FILE="$APP_DIR/.env"
[[ -f "$ENV_FILE" ]] || ENV_FILE="$(dirname "$APP_DIR")/.env"
[[ -f "$ENV_FILE" ]] || { echo "找不到 .env（$APP_DIR/.env），无法读取 OSS 凭据。" >&2; exit 1; }

# ── 读 OSS 凭据（只取需要的键，避免 source 整个文件踩坑）──
read_env() { grep -E "^$1=" "$ENV_FILE" | head -n1 | cut -d= -f2- | tr -d '"'\''' | tr -d '\r'; }
OSS_AK="$(read_env OSS_ACCESS_KEY_ID)"
OSS_SK="$(read_env OSS_ACCESS_KEY_SECRET)"
OSS_REGION="$(read_env OSS_REGION)"
OSS_BUCKET="$(read_env OSS_BUCKET)"
: "${OSS_REGION:=oss-cn-hangzhou}"
: "${OSS_BUCKET:=photo-intake}"
: "${R2_BUCKET:=photo-archive}"
[[ -n "$OSS_AK" && -n "$OSS_SK" ]] || { echo ".env 里缺 OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET。" >&2; exit 1; }
OSS_ENDPOINT="${OSS_REGION}.aliyuncs.com"
R2_ENDPOINT="https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

# ── 装 rclone ──
if ! command -v rclone >/dev/null 2>&1; then
  echo "==> 安装 rclone（官方脚本）"
  curl -fsSL https://rclone.org/install.sh | bash
else
  echo "==> rclone 已安装：$(command -v rclone)（$(rclone version | head -n1)）"
fi

# ── 确定运行后端的用户与其家目录 ──
RUN_USER="${2:-}"
if [[ -z "$RUN_USER" ]]; then
  RUN_USER="$(systemctl show "$SERVICE_NAME" -p User --value 2>/dev/null || true)"
fi
[[ -n "$RUN_USER" ]] || RUN_USER="root"
RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"
[[ -n "$RUN_HOME" ]] || { echo "找不到用户 $RUN_USER 的家目录。" >&2; exit 1; }
echo "==> 后端运行用户：$RUN_USER（家目录 $RUN_HOME）"

# ── 写 rclone.conf ──
CONF_DIR="$RUN_HOME/.config/rclone"
CONF="$CONF_DIR/rclone.conf"
mkdir -p "$CONF_DIR"
cat > "$CONF" <<EOF
[oss]
type = s3
provider = Alibaba
access_key_id = $OSS_AK
secret_access_key = $OSS_SK
endpoint = $OSS_ENDPOINT

[r2]
type = s3
provider = Cloudflare
access_key_id = $R2_ACCESS_KEY_ID
secret_access_key = $R2_SECRET_ACCESS_KEY
endpoint = $R2_ENDPOINT
EOF
chmod 600 "$CONF"
chown -R "$RUN_USER":"$(id -gn "$RUN_USER")" "$CONF_DIR"
echo "==> 已写 $CONF（600，属主 $RUN_USER）"

# ── 自检：以运行用户身份列两个桶 ──
echo "==> 自检 OSS（oss:$OSS_BUCKET）"
sudo -u "$RUN_USER" rclone lsd "oss:$OSS_BUCKET" --max-depth 1 >/dev/null \
  && echo "   ✓ OSS 可访问" || { echo "   ✗ OSS 访问失败，检查 OSS 凭据/endpoint" >&2; exit 2; }
echo "==> 自检 R2（r2:$R2_BUCKET 桶内，空桶也算通过）"
sudo -u "$RUN_USER" rclone lsd "r2:$R2_BUCKET" >/dev/null \
  && echo "   ✓ R2 可访问" || { echo "   ✗ R2 访问失败，检查 R2 凭据/account id/桶名/token 权限" >&2; exit 2; }

# ── 重启后端，让 shutil.which('rclone') 与 PATH 立即生效 ──
echo "==> 重启 $SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo
echo "✓ 完成。App「投稿管理」里 R2 徽章应变为「可归档」，点「一键归档」即可。"
echo "  手动验证：curl -s -H 'X-Intake-Admin-Token: <口令>' 'http://127.0.0.1:8000/api/intake/admin/archive/status' "
