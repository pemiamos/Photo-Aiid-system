#!/usr/bin/env python3
"""
Photo-Aiid-system · 一键启动脚本
同时启动前端 (Vite) 和后端 (FastAPI)，自动打开浏览器。
用法: python start.py
"""

import subprocess
import sys
import os
import time
import webbrowser
import signal
import platform

ROOT = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(ROOT, "frontend")
BACKEND_DIR = os.path.join(ROOT, "backend")

FRONTEND_URL = "http://localhost:5173"
BACKEND_URL = "http://localhost:8000"

processes = []


def log(msg):
    print(f"\033[93m[Photo-Aiid-system]\033[0m {msg}")


def check_prerequisites():
    """检查前置依赖"""
    errors = []

    # 检查 Node.js
    try:
        result = subprocess.run(["node", "--version"], capture_output=True, text=True)
        log(f"✓ Node.js {result.stdout.strip()}")
    except FileNotFoundError:
        errors.append("Node.js 未安装。请访问 https://nodejs.org/ 安装。")

    # 检查 Python
    log(f"✓ Python {platform.python_version()}")

    # 检查前端依赖
    if not os.path.exists(os.path.join(FRONTEND_DIR, "node_modules")):
        log("📦 前端依赖未安装，正在安装...")
        subprocess.run(["npm", "install"], cwd=FRONTEND_DIR, check=True)
        log("✓ 前端依赖安装完成")

    # 检查后端依赖
    try:
        import fastapi
        log(f"✓ FastAPI {fastapi.__version__}")
    except ImportError:
        log("📦 后端依赖未安装，正在安装...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r",
             os.path.join(BACKEND_DIR, "requirements.txt")],
            check=True
        )
        log("✓ 后端依赖安装完成")

    if errors:
        for e in errors:
            log(f"❌ {e}")
        sys.exit(1)


def start_backend():
    """启动 FastAPI 后端"""
    log("🚀 启动后端服务 (FastAPI @ :8000)...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--reload",
         "--reload-exclude", "*.db",
         "--reload-exclude", "*.db-*",
         "--reload-exclude", "*.log",
         "--host", "0.0.0.0", "--port", "8000"],
        cwd=BACKEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    processes.append(proc)
    return proc


def start_frontend():
    """启动 Vite 前端"""
    log("🚀 启动前端服务 (Vite @ :5173)...")
    proc = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=FRONTEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    processes.append(proc)
    return proc


def open_browser():
    """等待服务就绪后打开浏览器"""
    import urllib.request
    log("⏳ 等待服务启动...")
    for i in range(30):
        try:
            urllib.request.urlopen(FRONTEND_URL, timeout=1)
            log(f"✓ 前端已就绪: {FRONTEND_URL}")
            webbrowser.open(FRONTEND_URL)
            return
        except Exception:
            time.sleep(1)
    log("⚠️ 前端启动超时，请手动打开浏览器访问 " + FRONTEND_URL)


def cleanup(sig=None, frame=None):
    """清理子进程"""
    log("\n🛑 正在关闭所有服务...")
    for proc in processes:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    log("👋 已退出")
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    log("=" * 50)
    log("Photo-Aiid-system · AI 智能照片管理系统")
    log("=" * 50)

    check_prerequisites()

    backend_proc = start_backend()
    time.sleep(2)  # 给后端一点启动时间

    frontend_proc = start_frontend()

    open_browser()

    log("")
    log("✅ 所有服务已启动！")
    log(f"   前端: {FRONTEND_URL}")
    log(f"   后端: {BACKEND_URL}")
    log(f"   API 文档: {BACKEND_URL}/docs")
    log("")
    log("按 Ctrl+C 停止所有服务")
    log("")

    # 监控子进程
    try:
        while True:
            # 检查进程是否意外退出
            if backend_proc.poll() is not None:
                log("⚠️ 后端进程已退出，正在重启...")
                backend_proc = start_backend()
            if frontend_proc.poll() is not None:
                log("⚠️ 前端进程已退出")
                break
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()


if __name__ == "__main__":
    main()
