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

echo "==> [1/5] 构建前端 (vite build)"
( cd frontend && npm run build )

# 本地视觉预分类是可选功能：装不上依赖/没有模型时 spec 会自动排除，
# 打出来的包不带预分类，其余功能不受影响。这里尽力装一次，失败不中断。
echo "==> [2/5] 可选依赖：本地视觉预分类"
if "$VENV/bin/pip" install -q -r backend/requirements-fast.txt 2>/dev/null; then
  if "$VENV/bin/python" scripts/download-fast-models.py --check >/dev/null 2>&1; then
    echo "    ✓ 依赖与模型就绪，将随包打入（+约 148MB）"
  else
    echo "    ⚠ 依赖已装但模型缺失 —— 本次打包不含预分类"
    echo "      需要的话先跑：$VENV/bin/python scripts/download-fast-models.py"
  fi
else
  echo "    ⚠ 可选依赖安装失败 —— 本次打包不含预分类"
fi

echo "==> [3/5] 冻结 Python 后端 (PyInstaller)"
if [ ! -x "$VENV/bin/pyinstaller" ]; then
  echo "错误：未找到打包虚环境 $VENV。请先创建并安装依赖。" >&2
  exit 1
fi
( cd backend && rm -rf build dist && "$VENV/bin/pyinstaller" photo_aiid_backend.spec --noconfirm )

echo "==> [4/5] 拷贝后端到 Tauri 资源目录"
rm -rf "$TAURI_RES"
mkdir -p "$(dirname "$TAURI_RES")"
cp -R "$BACKEND_FREEZE" "$TAURI_RES"

echo "==> [5/5] 编译 Tauri App (.app + .dmg)"
# 确保 cargo 在 PATH 中
[ -f "$HOME/.cargo/env" ] && source "$HOME/.cargo/env"
npx tauri build

echo
echo "✅ 完成。产物位于："
echo "   src-tauri/target/release/bundle/macos/Photo-Aiid-system.app"
echo "   src-tauri/target/release/bundle/dmg/*.dmg"
