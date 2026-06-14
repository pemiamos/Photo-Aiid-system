"""
Photo-Aiid-system · 打包入口 (frozen entry point)

被 PyInstaller 冻结为独立可执行文件。启动前把数据库 / 缩略图缓存指向用户可写目录
(打包后 .app 内部只读)，然后以编程方式拉起 uvicorn。

开发期也可直接运行: python backend/run_server.py
"""

import os
import sys
from pathlib import Path


def _app_support_dir() -> Path:
    """返回一个跨平台的用户可写数据目录，并确保存在。"""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Photo-Aiid-system"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home()))) / "Photo-Aiid-system"
    else:
        base = Path.home() / ".photo-aiid-system"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _resource_dir() -> Path:
    """打包后资源被解包到 sys._MEIPASS；开发期就是本文件所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent


# 必须在导入 main / database 之前设置——这些模块在 import 时即读取环境变量。
_data = _app_support_dir()
os.environ.setdefault("PHOTO_AIID_DB", str(_data / "photo_aiid.db"))
os.environ.setdefault("PHOTO_AIID_THUMB_DIR", str(_data / "thumbnails"))
os.environ.setdefault("PHOTO_AIID_DIST", str(_resource_dir() / "frontend_dist"))

import uvicorn  # noqa: E402
from main import app  # noqa: E402


def main() -> None:
    host = os.environ.get("PHOTO_AIID_HOST", "127.0.0.1")
    port = int(os.environ.get("PHOTO_AIID_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
