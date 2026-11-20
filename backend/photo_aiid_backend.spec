# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 配置 · Photo-Aiid-system 后端

从 backend/ 目录运行:
    pyinstaller photo_aiid_backend.spec --noconfirm

产物: dist/photo-aiid-backend/  (onedir，含可执行文件 photo-aiid-backend)
"""

import os
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_submodules,
    collect_dynamic_libs,
)

HERE = os.path.abspath(os.getcwd())  # 约定从 backend/ 目录运行

# ── 本地视觉预分类（可选）──────────────────────────────────────────────────
# 模型不入 git（见 .gitignore 的 backend/models/），本地跑过
# scripts/download-fast-models.py 才会存在。存在则随包带上（+148MB），
# 不存在则整块排除——这样 CI 上没有模型时产物体积与原来一致。
_models = os.path.join(HERE, "models")
_fast_models = (os.path.isdir(_models)
                and any(f.endswith(".onnx") for f in os.listdir(_models)))

# ── 数据文件 ──────────────────────────────────────────────────────────────
datas = []
# reverse_geocoder 自带城市坐标 CSV，必须随包带上
datas += collect_data_files("reverse_geocoder")

# 前端构建产物（若已 build），打进包内供后端同源托管
_dist = os.path.join(HERE, "..", "frontend", "dist")
if os.path.isdir(_dist):
    datas += [(_dist, "frontend_dist")]

# 预分类模型 + 页面文件
if _fast_models:
    datas += [(_models, "models")]
datas += [(os.path.join(HERE, "fast_review.html"), ".")]

# ── 隐藏导入 ──────────────────────────────────────────────────────────────
hiddenimports = []
# uvicorn 的 loop/protocol/lifespan 实现是运行时动态加载的，需显式带上
hiddenimports += collect_submodules("uvicorn")
hiddenimports += ["aiosqlite", "exifread"]

if _fast_models:
    hiddenimports += ["onnxruntime", "cv2", "tokenizers"]
    datas += collect_data_files("onnxruntime")

# pillow-heif：HEIC/HEIF 解码。含编译扩展 _pillow_heif 与 libheif 动态库，
# 必须显式收集，否则打包后 PIL 仍打不开 .heic。
heif_binaries = []
try:
    hiddenimports += collect_submodules("pillow_heif")
    datas += collect_data_files("pillow_heif")
    heif_binaries += collect_dynamic_libs("pillow_heif")
except Exception:
    pass

# 本地视觉预分类的动态库（仅在有模型时）。
#   onnxruntime：依赖 hooks-contrib 的 hook-onnxruntime.py；2024 年前的版本没有
#     这个 hook，所以这里显式收一次，避免冻结版 import onnxruntime 报缺 dylib。
#   cv2：官方 hook-cv2.py 里 collect_dynamic_libs("cv2") **只在 compat.is_win
#     分支执行**。mac 的 opencv wheel 自带 70 个 .dylib（cv2/.dylibs/ 下有
#     ffmpeg / x265 / openssl / gnutls 全套），不显式收就会在冻结版里报
#     `Library not loaded: @rpath/libavcodec...`。
if _fast_models:
    for _pkg in ("onnxruntime", "cv2"):
        try:
            heif_binaries += collect_dynamic_libs(_pkg)
        except Exception:
            pass

# ── 排除 ──────────────────────────────────────────────────────────────────
# clip 引擎是可选的；torch/sentence_transformers 体积巨大且非必需，排除后
# engines/__init__ 的 try/except 会自动跳过 CLIP，系统仍可用云端引擎。
# macOS 文件夹选择走 osascript，无需 tkinter。
excludes = [
    "torch",
    "sentence_transformers",
    "transformers",
    "tkinter",
    "matplotlib",
    "pandas",
    "tests",
]

# 没有模型时不打包预分类的依赖（保持 CI 产物体积不变）
if not _fast_models:
    excludes += ["onnxruntime", "cv2", "tokenizers", "huggingface_hub"]

a = Analysis(
    ["run_server.py"],
    pathex=[HERE],
    binaries=heif_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="photo-aiid-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="photo-aiid-backend",
)
