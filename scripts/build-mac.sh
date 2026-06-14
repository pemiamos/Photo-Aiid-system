#!/usr/bin/env bash
#
# Photo-Aiid-system · 一键打包 macOS App
#
# 步骤：构建前端 → 冻结 Python 后端 → 拷贝为 Tauri 资源 → 编译 .app/.dmg
#
# 前置：已装 Python 3.12 打包虚环境 (.venv-build)、Node、Rust、Tauri CLI。
# 用法：bash scripts/build-mac.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV="$ROOT/.venv-build"
BACKEND_FREEZE="$ROOT/backend/dist/photo-aiid-backend"
TAURI_RES="$ROOT/src-tauri/resources/backend"

echo "==> [1/4] 构建前端 (vite build)"
( cd frontend && npm run build )

echo "==> [2/4] 冻结 Python 后端 (PyInstaller)"
if [ ! -x "$VENV/bin/pyinstaller" ]; then
  echo "错误：未找到打包虚环境 $VENV。请先创建并安装依赖。" >&2
  exit 1
fi
( cd backend && rm -rf build dist && "$VENV/bin/pyinstaller" photo_aiid_backend.spec --noconfirm )

echo "==> [3/4] 拷贝后端到 Tauri 资源目录"
rm -rf "$TAURI_RES"
mkdir -p "$(dirname "$TAURI_RES")"
cp -R "$BACKEND_FREEZE" "$TAURI_RES"

echo "==> [4/4] 编译 Tauri App (.app + .dmg)"
# 确保 cargo 在 PATH 中
[ -f "$HOME/.cargo/env" ] && source "$HOME/.cargo/env"
npx tauri build

echo
echo "✅ 完成。产物位于："
echo "   src-tauri/target/release/bundle/macos/Photo-Aiid-system.app"
echo "   src-tauri/target/release/bundle/dmg/*.dmg"
