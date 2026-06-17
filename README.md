# Photo-Aiid-system

> AI 照片管理 + 网页征稿协作系统

[![Version](https://img.shields.io/badge/version-3.1.0-orange.svg)]()
[![License](https://img.shields.io/badge/license-CC%20BY--NC--SA%204.0-lightgrey.svg)]()
[![Python](https://img.shields.io/badge/python-3.10+-green.svg)]()
[![React](https://img.shields.io/badge/react-18+-61dafb.svg)]()

桌面端在本机就地整理照片（AI 识别 / 批量重命名 / 语义搜索），**v3.0 起**扩展出一整套
**网页征稿 + 云端投稿管理 + OSS/R2 双云存储**，把「编辑整理」和「多人投稿协作」收进同一个 App。

---

## ✨ 功能亮点

### 本地照片整理（桌面 App）
- 🕘 **历史索引** ⭐ — **最适合普通用户管理照片的功能**。不必记得照片存到哪个文件夹，只要曾经分析过，就能在索引表里**跨全库**按摄影师 / 地点 / 标签 / 类别 / 文件名一键秒搜，相当于给整个照片库建了一座可搜索的「历史档案馆」（「去年在南京拍的那批」「张三投的稿」「所有带『日落』标签的」——输入关键词即出）
- 🤖 **AI 自动识别** — 智能分类、打标、提取摄影师与拍摄地点，强 JSON 模式 + 安全校验
- 🔀 **多引擎切换** — 本地 Ollama / CLIP（隐私优先）或云端 **智谱 GLM（glm-4v-flash 免费）** / Claude / Gemini
- 👤 **摄影师识别** — 从文件名/文件夹提取摄影师（含昵称、网名、拼音），结构化入库
- 📍 **拍摄地点** — 有 GPS 时**离线反向地理编码**到中文市/县级（内置 3238 条行政区划，不联网）；无 GPS 时由 AI 推断
- 🏷️ **EXIF 提取** + ✏️ **人工校正**（单张/批量改标签与地点）
- 📁 **可视化重命名** — 拖拽式模板构建器 + 实时预览 + 空字段省略 + 物理重命名 + CSV 日志
- 🚀 **极速增量扫描** — 共享 SQLite 长连接 + 多核并发，二次扫描毫秒级
- 🖱️ **拖拽到桌面** — 缩略图拖出即复制原图（已分析的用新文件名）
- 🔍 **语义搜索** · 📊 **CSV 导出** · 🌓 **专业暗色 UI**

### 网页征稿与云端协作（v3.0 新增）
- 🌐 **网页投稿** — 摄影师凭**投稿码**打开专属链接即可上传，无需装任何软件；照片**浏览器直传 OSS**（STS 临时凭证，不过服务器）
- 🗂️ **云端投稿管理** — App「投稿管理」远程连接征稿服务器：建书籍项目、发投稿码（单个/批量）、生成专属链接与**二维码**
- 📊 **征稿看板** — 已交/未交统计、按投稿码**下钻看缩略图墙 + 放大查看**、搜索/筛选/排序、**一键复制未交催稿名单/链接**、自动刷新
- ☁️ **OSS 主存 + R2 持续备份** — 阿里云 OSS 长期主存（国内读写快），云端服务器每 15 分钟自动增量镜像到 Cloudflare R2 异地容灾（只增不删），App 徽章实时反映备份成败
- 🔐 **口令头鉴权** — 远程管理用 `X-Intake-Admin-Token`，云端只暴露征稿接口、无画廊/照片接口，天然隔离

### 跨平台
- 💻 源码运行（浏览器，Mac / Windows / Linux）或安装打包版桌面应用（Mac / Windows）

---

## 🚀 快速开始（本地开发）

### 前置要求
- [Node.js](https://nodejs.org/) 18+ · [Python](https://python.org/) 3.10+

### 一键启动
```bash
python start.py
```
脚本会自动安装依赖、启动前后端、打开浏览器。

### 手动启动
```bash
# 后端
cd backend && python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt && uvicorn main:app --reload

# 前端
cd frontend && npm install && npm run dev
```
访问 http://localhost:5173

---

## 📦 桌面应用（打包版）

无需安装 Node/Python，直接安装即用：

- **macOS**：拖入「应用程序」双击启动（首次需右键打开以绕过 Gatekeeper）
- **Windows**：运行 NSIS 安装包

桌面版基于 [Tauri](https://tauri.app/) 封装，内置冻结的 Python 后端，本机自动启动/退出。详细使用说明见 [docs/使用教程.md](docs/使用教程.md)，App 内「使用教程」标签也有同样内容。

### 本地构建
```bash
# macOS（需 Node、Rust、Python 3.12 打包虚环境 .venv-build）
bash scripts/build-mac.sh

# Windows（需 Node、Rust(MSVC)、Python 3.12 打包虚环境 .venv-build）
powershell -ExecutionPolicy Bypass -File scripts/build-win.ps1
```
也可在 GitHub Actions 手动触发 `.github/workflows/build-windows.yml` 自动构建 Windows 安装包。

---

## 🌐 网页征稿与云端投稿管理（v3.0）

一套「公网征稿后端 + App 远程管理」的协作链路：摄影师用网页投稿，编辑用桌面 App 远程管理。

```
摄影师浏览器 ──投稿码校验──> 云端后端(intake.sdexp.org)
            ──STS 临时凭证──> 阿里云 OSS(photo-intake)   ← 原图直传，不过服务器
编辑(桌面App「投稿管理」) ──口令头远程管理──> 云端后端   （建书 / 发码 / 看板 / 下钻看图）
云端服务器(systemd timer 每15min) ──rclone 增量镜像──> Cloudflare R2(photo-archive) ← 异地备份
```

- **读取始终走 OSS**（国内最快）；**R2 只写不读**，仅作容灾副本。默认**不清空 OSS**（双云各留一份）。
- 部署征稿后端见 [docs/部署到阿里云.md](docs/部署到阿里云.md)；OSS/R2 配置见 [docs/OSS接入配置.md](docs/OSS接入配置.md)；
  完整开码到归档流程见 [docs/征稿工作流程.md](docs/征稿工作流程.md)；下载选图见 [docs/下载到本地教程.md](docs/下载到本地教程.md)。

---

## 🏗️ 项目结构

```
Photo-Aiid-system/
├── frontend/              # React + Vite 前端（画廊 / 索引 / 投稿管理 / 使用教程）
├── backend/               # Python FastAPI 后端
│   ├── engines/           # AI 引擎 (zhipu / claude / gemini / ollama / clip)
│   ├── services/          # 业务逻辑 (扫描 / 分析 / 重命名 / 离线地理编码)
│   ├── data/              # 中国行政区划数据 (离线反向地理编码)
│   ├── main.py            # 本地完整后端入口（画廊 + AI + 征稿）
│   ├── intake_server.py   # 云端精简后端入口（仅征稿，部署到服务器）
│   └── intake.py          # 征稿路由（投稿码 / OSS 直传 / 看板 / 下钻 / 备份状态）
├── src-tauri/             # 桌面应用外壳 (Tauri)
├── deploy/                # 云端部署模板 (systemd service / nginx)
├── scripts/               # 打包构建 + 云端运维脚本
│   ├── build-mac.sh / build-win.ps1        # 桌面打包
│   ├── deploy-server.sh                     # 一键部署征稿后端到服务器
│   ├── setup-rclone.sh                      # 服务器装配 rclone
│   ├── mirror-oss-to-r2.sh / install-r2-mirror.sh   # OSS→R2 持续镜像 (systemd timer)
│   └── archive-to-r2.sh / sync-to-r2.sh / export-intake-meta.py
├── docs/                  # 使用教程、征稿/部署/下载文档、历史归档
├── start.py               # 一键启动脚本
└── README.md
```

---

## 🔧 AI 引擎配置

| 引擎 | 类型 | 说明 |
|------|------|------|
| **智谱 GLM** | 云端 | `glm-4v-flash` **免费**、中文友好。[获取 Key](https://open.bigmodel.cn/) |
| **Ollama** | 本地 | 免费、离线、不上传。需安装 [Ollama](https://ollama.ai/) 并下载视觉模型（如 `gemma3`） |
| **Claude** | 云端 | 高精度，需 API Key。[获取 Key](https://console.anthropic.com/) |
| **Gemini** | 云端 | 需 API Key，注意区域免费额度。[获取 Key](https://aistudio.google.com/apikey) |
| **CLIP** | 本地 | 免费、离线、快速分类（仅类别/标签）。需 `pip install sentence-transformers` |

> 所有引擎共用同一识别链路（摄影师/地点/EXIF/相邻序列上下文）。密钥仅保存在本机数据库，不上传第三方。

---

## 📝 API 文档

启动后端后访问 http://localhost:8000/docs 查看交互式 API 文档。

---

## 📄 License

[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) · 星尘远征队 出品
