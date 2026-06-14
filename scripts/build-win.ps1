# Photo-Aiid-system - 一键打包 Windows App
#
# 步骤：构建前端 -> 冻结 Python 后端 -> 拷贝为 Tauri 资源 -> 编译 .exe/.msi
#
# 前置：已装 Python 3.12、Node、Rust(MSVC toolchain)、Tauri CLI。
# 用法：powershell -ExecutionPolicy Bypass -File scripts/build-win.ps1

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Venv = Join-Path $Root ".venv-build"
$BackendFreeze = Join-Path $Root "backend\dist\photo-aiid-backend"
$TauriRes = Join-Path $Root "src-tauri\resources\backend"

Write-Host "==> [1/4] 构建前端 (vite build)"
Push-Location frontend
npm run build
Pop-Location

Write-Host "==> [2/4] 冻结 Python 后端 (PyInstaller)"
$Pyinstaller = Join-Path $Venv "Scripts\pyinstaller.exe"
if (-not (Test-Path $Pyinstaller)) {
    Write-Error "未找到打包虚环境 $Venv。请先创建并安装依赖。"
    exit 1
}
Push-Location backend
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
& $Pyinstaller photo_aiid_backend.spec --noconfirm
Pop-Location

Write-Host "==> [3/4] 拷贝后端到 Tauri 资源目录"
Remove-Item -Recurse -Force $TauriRes -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $TauriRes | Out-Null
Copy-Item -Recurse -Force "$BackendFreeze\*" $TauriRes

Write-Host "==> [4/4] 编译 Tauri App (.exe / .msi)"
npx tauri build

Write-Host ""
Write-Host "完成。产物位于："
Write-Host "   src-tauri\target\release\bundle\nsis\*.exe"
Write-Host "   src-tauri\target\release\bundle\msi\*.msi"
