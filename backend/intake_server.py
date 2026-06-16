"""
Photo-Aiid-system · 征稿云端精简后端

只承载「投稿征稿」一块（投稿网页 + 验码/签名/看板接口），不含画廊、AI 分析、
设置等本机功能——这些接口在云端根本不存在，天然只暴露 /intake 与 /api/intake/*。

部署在公网服务器上（见 docs/部署到阿里云.md）。本机开发仍用完整的 main.py。

运行：
    uvicorn intake_server:app --host 127.0.0.1 --port 8000

依赖：requirements-server.txt（fastapi/uvicorn/aiosqlite/httpx/python-multipart）。
环境变量（建议放同目录 .env，由下方加载）：
    OSS_REGION / OSS_BUCKET / OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET / OSS_STS_ROLE_ARN
    INTAKE_ADMIN_TOKEN   管理口令（桌面 App 远程管理用，务必设置）
    INTAKE_BOOK / INTAKE_BOOK_TITLE  默认书目（可选，多书时由后台创建）
    PHOTO_AIID_DB        SQLite 路径（默认当前目录 photo_aiid.db）
    INTAKE_DATA          本地直存目录（OSS 模式下基本用不到）
"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

# 在 import intake 之前把 .env 注入环境变量（intake.py 在模块顶层读取 OSS_* 等）。
# 与 main.py 一致：同时找上级目录（仓库根）与本级目录的 .env；setdefault 使真实
# export 的环境变量优先于文件。无第三方依赖，逐行解析 KEY=VALUE。
def _load_dotenv() -> None:
    here = Path(__file__).resolve().parent
    for envfile in (here.parent / ".env", here / ".env"):
        if not envfile.is_file():
            continue
        for raw in envfile.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import database as db
import intake

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("intake-server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    await intake.init_intake_db()
    mode = "OSS 直传" if intake._oss_configured() else "本地直存"
    logger.info("征稿云端后端已启动 ✓（上传模式：%s）", mode)
    if not intake.ADMIN_TOKEN:
        logger.warning("未设置 INTAKE_ADMIN_TOKEN，后台无鉴权！公网部署务必设置。")
    yield


app = FastAPI(title="Photo-Aiid 征稿", version="2.0.0", lifespan=lifespan)

# 公网征稿接口：放开跨域。管理接口靠 X-Intake-Admin-Token 头鉴权（见 intake.require_admin），
# 不依赖 Cookie，故无需 allow_credentials。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(intake.router)


@app.get("/healthz")
async def healthz():
    return {"ok": True}
