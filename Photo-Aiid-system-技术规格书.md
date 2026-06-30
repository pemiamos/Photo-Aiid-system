# Photo-Aiid-system · 技术规格书

> **AI 照片管理 + 网页征稿协作系统**
> 版本：v3.1.4 · 桌面端本地整理 + 云端网页征稿
> 日期：2026-06-30
> 作者：pemiamos × AI 协作（Claude / Codex / AG 接力）
> 状态：**已完工并发布**（本文档描述已实现的系统，非规划稿）

---

## 1. 项目愿景

一款**轻量、隐私优先**的照片智能管理工具，并扩展出一套面向多人协作的**网页征稿 + 云端投稿管理**链路：

- **桌面端**：在用户本机就地整理照片——AI 自动识别内容、提取摄影师/地点、批量重命名、跨全库语义找图，原图不复制、不上传、不移动。
- **云端征稿（v3.0 起）**：摄影师凭投稿码用浏览器直传照片到对象存储，编辑在桌面 App 内远程建项目、发码、看板下钻；OSS 主存 + R2 异地容灾。

两端收进同一个 App：左侧本地整理，「投稿管理」标签远程协作。Mac / Windows 通用，既可源码运行（浏览器），也有 Tauri 打包的桌面安装版。

---

## 2. 技术架构

### 2.1 架构总览

桌面端采用 **Web 前端 + 本地 Python 后端** 的混合架构，由 Tauri 套壳为原生桌面 App；云端征稿是一份**精简后端**单独部署到公网服务器。

```
┌──────────────────────── 桌面 App (Tauri 外壳) ────────────────────────┐
│  前端: React + Vite (画廊 / 索引表 / 历史索引 / 投稿管理 / 使用教程)   │
│        拖入照片 → 预览 → AI 分析 → 校正 → 批量重命名 → 导出           │
└───────────────┬───────────────────────────────┬──────────────────────┘
                │ HTTP REST (localhost:8000)     │ 口令头远程管理
┌───────────────▼───────────────────┐           │
│  本地后端: Python (FastAPI, main)  │           │
│  ┌─────────────┐ ┌──────────────┐  │           │
│  │ 本地引擎     │ │ 云端引擎      │  │           │
│  │ ·Ollama     │ │ ·智谱 GLM     │  │           │
│  │ ·CLIP       │ │ ·Claude/Gemini│  │           │
│  └─────────────┘ └──────────────┘  │           │
│  ┌─────────────────────────────┐   │           │
│  │ 离线反向地理编码 (DataV 区划)│   │           │
│  │ SQLite 持久库 (多文件夹/历史)│   │           │
│  └─────────────────────────────┘   │           │
└────────────────────────────────────┘           │
                                                  ▼
                      ┌──────────────────────────────────────────┐
                      │  云端征稿后端: intake_server (FastAPI)     │
                      │  (intake.sdexp.org · 仅征稿接口、无画廊)    │
                      │   投稿码校验 · STS 临时凭证 · 看板/下钻     │
                      └───────────┬──────────────────┬───────────┘
        摄影师浏览器 ──直传原图──> │ 阿里云 OSS(主存) │ ──rclone 每15min──> Cloudflare R2(容灾)
                      └──────────────────┘
```

### 2.2 技术栈

| 维度 | 技术选型 | 说明 |
|------|----------|------|
| **前端** | React 18 + Vite | 现代化 UI、热更新、跨平台 |
| **桌面外壳** | Tauri 2 (Rust) | 内置冻结的 Python 后端，本机自动启停 |
| **后端** | Python 3.10+ + FastAPI | 异步高性能，AI 生态丰富 |
| **本地推理** | Ollama / CLIP (ONNX) | 完全离线、免费、隐私优先 |
| **云端 AI** | 智谱 GLM / Claude / Gemini | 高精度，需 API Key（仅存本机） |
| **数据库** | SQLite (aiosqlite) | 轻量、零配置、多文件夹持久库 |
| **图像处理** | Pillow + pillow-heif | 缩略图、EXIF、HEIC/大图兼容 |
| **离线地理编码** | DataV 行政区划质心 + reverse_geocoder | 有 GPS 时不联网即可定位市/县级 |
| **对象存储** | 阿里云 OSS（主）+ Cloudflare R2（备） | STS 临时凭证浏览器直传 + rclone 异地镜像 |
| **打包发布** | PyInstaller + Tauri + GitHub Actions | Mac 本地打包；Win 推 tag 触发 CI |

### 2.3 为什么是 Web + Python + Tauri

| 对比维度 | SwiftUI | Electron | **Web + Python + Tauri（当前方案）** |
|----------|---------|----------|--------------------------------------|
| 跨平台 | ❌ 仅 macOS | ✅ 安装包 150MB+ | ✅ 浏览器即用 / Tauri 体积小 |
| AI 生态 | Apple Vision 有限 | 需桥接 Python | ✅ Python 原生 |
| 安装成本 | App Store | 800MB+ | 源码 `pip install` 或装一个 dmg/exe |
| 开发效率 | Swift 生态较小 | 复杂度高 | ✅ 前后端解耦，迭代快 |
| 桌面化 | 锁死 Apple | 重度框架 | ✅ Tauri 轻量套壳，一份代码两端复用 |

---

## 3. 核心数据模型（实际 SQLite 表）

后端数据库为 SQLite，关键表如下（详见 `backend/database.py`）：

```
photos                       # 照片主表（多文件夹持久库，换文件夹不清空）
├── id
├── file_name                # 当前文件名（物理重命名后更新）
├── original_name            # 首次扫描的原始文件名，重命名后不覆盖（供历史索引检索）
├── file_path / relative_path
├── file_size / file_mtime
└── folder / scan_session...

ai_results                   # AI 分析结果（一对一）
├── photo_id
├── category                 # 「主类·子类」二级类别（如 自然风光·日落）
├── tags                     # 3–6 个中文标签
├── description              # ≤30 字画面描述
├── location                 # 拍摄地点（市/县级）
├── photographer             # 摄影师姓名/昵称
├── slug                     # 英文短名（用于文件名）
├── engine                   # 使用的引擎标识
└── analyzed_at

exif_data                    # EXIF（拍摄日期、相机、镜头、光圈、ISO、GPS…）
settings                     # 引擎设置 / API Key / 命名模板（仅存本机）
scan_sessions                # 扫描会话与进度
```

> **历史索引**即建立在 `photos.original_name + ai_results.category/location/photographer` 之上的跨全库检索（`file_name LIKE ? OR original_name LIKE ? OR category LIKE ? …`），所以即便物理重命名后，原文件名里的地名/事件仍可被搜到。

云端征稿后端（`intake_server.py` / `intake.py`）维护投稿码、书籍项目、投稿记录与 OSS 对象索引，与本地库相互独立。

---

## 4. 核心功能模块

### A. 智能扫描与挂载（非侵入）

- **不复制、不上传、不移动**原图，仅读取路径与元数据。
- **递归扫描**子目录，跳过 `.` 开头隐藏目录与 macOS AppleDouble 伴随文件（`._xxx`）。
- **EXIF 提取**：拍摄日期、相机/镜头、光圈、ISO、焦距、GPS。
- **极速增量扫描**：共享 SQLite 长连接 + 多核并发，二次扫描毫秒级。
- **多文件夹持久库**：v3.1 起换文件夹不清空，浏览/分析过的文件夹累积进库。

### B. AI 识别引擎（Vision Engine）

四个引擎统一识别链路，用户在侧栏自由切换（提示词已抽到 `engines/prompt.py` 共享模块，行为一致）：

| 引擎 | 类型 | 特点 |
|------|------|------|
| **智谱 GLM** | 云端 | `glm-4v-flash` 免费、中文友好，推荐新手 |
| **Ollama** | 本地 | 免费、离线、隐私优先（如 `gemma3:12b`） |
| **Claude** | 云端 | 精度最高，按量计费 |
| **Gemini** | 云端 | `gemini-2.5-flash`，有免费额度 |
| **CLIP** | 本地 | 离线快速分类（仅类别/标签；打包版未内置） |

**识别产出**（强 JSON 模式 + 安全校验）：
- **二级类别**「主类·子类」：物种主体一律归「物种」并补子类（猛禽/鸣禽/菊科…）；文件名含具体地名/事件时主类优先采用它；否则用画面大类 + 细分子类；无法细分时省略「·子类」。
- **标签** 3–6 个、**画面描述** ≤30 字。
- **摄影师**：从文件名/文件夹提取（真名/昵称/网名/拼音）。
- **拍摄地点**：有 GPS 时**离线反向地理编码**到市/县级（DataV 区划质心最近邻，境外回退 `reverse_geocoder`）；无 GPS 时由 AI 结合文件名/地标推断。
- 综合利用文件名、文件夹路径、相邻序列上下文辅助分类。

### C. 自动化索引与重命名（Batch Engine）

- **动态索引表**：原文件名 · 类别 · 标签 · 摄影师 · 地点 · 拍摄日期 · 建议新名。
- **可视化重命名**：拖拽式字段块模板（如 `[摄影师]_[地点]_[类别]_[日期]_[序号]`）+ 实时预览 + 空字段省略 + 自动去重。
- **物理重命名**：直接改写磁盘文件名，`original_name` 不覆盖以保留可追溯性。
- **CSV 重命名日志**：旧名 → 新名，每次自动导出。

### D. 检索系统（Search & Retrieval）

- **历史索引** ⭐：跨所有分析过的文件夹按摄影师/地点/标签/类别/文件名（含原名）一键秒搜；附最近搜索词与整库高频标签快捷入口。
- **关键词过滤**：按标签、类别、日期等实时筛选。
- **语义搜索**：将标签/描述索引发送给所选 LLM 引擎做语义匹配，返回排序后的照片 id（CLIP 引擎不支持语义搜索）。

### E. 拖拽与导出

- **拖拽到桌面**：画廊缩略图拖出即复制原图（已分析的用新文件名）。
- **CSV 索引导出**（Excel/Numbers 可开）。
- **人工校正**：单张/批量修改标签与地点。

### F. 网页征稿与云端投稿管理（v3.0）

- **网页投稿**：摄影师凭投稿码打开专属链接上传，无需装软件；照片经 **STS 临时凭证浏览器直传 OSS**，不过服务器。
- **云端投稿管理**：App「投稿管理」远程连接征稿后端——建书籍项目、发投稿码（单个/批量）、生成专属链接与二维码。
- **征稿看板**：已交/未交统计、按投稿码下钻看缩略图墙 + 放大、搜索/筛选/排序、一键复制未交催稿名单/链接、自动刷新。
- **双云存储**：OSS 长期主存（国内读写快），服务器 systemd timer 每 15 分钟用 rclone 增量镜像到 Cloudflare R2（只增不删）异地容灾，App 徽章实时反映备份成败；读取始终走 OSS。
- **口令头鉴权**：远程管理用 `X-Intake-Admin-Token`，云端只暴露征稿接口、无画廊/照片接口，天然隔离。

---

## 5. API 设计

### 5.1 本地后端（`backend/main.py`，localhost:8000）

```
GET    /api/health                  # 健康检查 + 引擎状态
POST   /api/scan                    # 挂载文件夹、开始扫描
GET    /api/scan/progress           # 扫描进度
GET    /api/folders                 # 已挂载文件夹列表
POST   /api/folders/remove|clear|clean-stale
GET    /api/photos                  # 照片列表（分页/过滤）
GET    /api/photos/{id}             # 单张详情
POST   /api/photos/ai/batch         # 批量取 AI 结果
GET    /api/thumbnails/{id}         # 缩略图
GET    /api/originals/{id}          # 原图
POST   /api/analyze                 # 触发分析（全局/自选）
POST   /api/analyze/pause|resume|cancel
POST   /api/analyze/{id}            # 重新分析单张
GET    /api/analyze/progress
POST   /api/rename                  # 执行批量重命名
POST   /api/rename/preview          # 重命名预览
GET    /api/search                  # 关键词/历史索引搜索
POST   /api/search/semantic         # LLM 语义搜索
GET    /api/tags                    # 标签云
GET    /api/settings  · PUT /api/settings
GET    /api/export/csv              # 导出索引 CSV
POST   /api/test-engine             # 测试引擎连接
POST   /api/select-folder           # 原生选目录
```

### 5.2 云端征稿后端（`backend/intake.py`，intake.sdexp.org）

```
# 摄影师侧（公开）
GET    /intake                      # 投稿页
POST   /api/intake/verify           # 投稿码校验
POST   /api/intake/sts              # 申请 OSS STS 临时凭证
POST   /api/intake/record|complete  # 登记/完成投稿
GET    /api/intake/oss-config

# 编辑侧（口令头 X-Intake-Admin-Token 鉴权）
POST   /api/intake/admin/login|logout
GET/POST  /api/intake/admin/books   · POST .../books/{code}/status
GET/POST/DELETE  /api/intake/admin/codes  · POST .../codes/batch
GET    /api/intake/admin/submissions      # 看板数据
GET    /api/intake/admin/files            # 投稿码下钻文件
GET    /api/intake/admin/file/raw         # 单图原图
GET    /api/intake/admin/export.csv       # 导出
POST   /api/intake/admin/archive          # 触发归档
GET    /api/intake/admin/archive/status   # 备份状态
GET    /api/intake/admin/ping
```

---

## 6. UI 设计

```
┌─────────────────────────────────────────────────────────────┐
│  Photo-Aiid-system                          [vX.Y.Z 徽章]    │
├─────────────────────────────────────────────────────────────┤
│ ┌─────────┐ ┌─────────────────────────────────────────────┐ │
│ │ 选择文件夹│ │ [ 画廊 ] [ 索引表/历史索引 ] [ 投稿管理 ] [ 使用教程 ] │
│ │ 识别引擎  │ │  🔍 搜索 / 语义搜索                         │ │
│ │ ·智谱GLM  │ │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐          │ │
│ │ ·Ollama   │ │  │ img │ │ img │ │ img │ │ img │  瀑布流   │ │
│ │ ·Claude   │ │  │ tag │ │ tag │ │ tag │ │ tag │          │ │
│ │ ·Gemini   │ │  └─────┘ └─────┘ └─────┘ └─────┘          │ │
│ │ 命名模板  │ │  [⚡ 全局/自选分析] [✏️ 重命名] [📥 导出]   │ │
│ │ 标签过滤  │ ├─────────────────────────────────────────────┤ │
│ │ 库统计    │ │  详情 / 批量校正 / 看板下钻                  │ │
│ └─────────┘ └─────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

- **暗色主题**为主（摄影师友好），琥珀色 (Amber) 为品牌强调色。
- 等宽字体用于元数据；瀑布流 (Masonry) 画廊，解除张数上限、渐进式渲染，几万张不卡。
- 顶部徽章自动显示真实版本号。

---

## 7. 性能与隐私规范

| 维度 | 要求 / 实现 |
|------|-------------|
| **隐私** | 原图不复制/不上传/不移动；Ollama/CLIP 完全离线；云端引擎为可选项 |
| **API Key 安全** | 仅存本机 SQLite `settings`，不上传第三方 |
| **离线地理编码** | 有 GPS 时不联网即可定位市/县级（内置区划质心） |
| **扫描性能** | 共享 SQLite 长连接 + 多核并发，增量二次扫描毫秒级 |
| **缓存** | 分析结果持久化，按文件指纹避免重复推理 |
| **图像兼容** | pillow-heif 支持 HEIC 与超大图缩略图/分析 |
| **征稿安全** | STS 临时凭证直传、口令头鉴权、云端无画廊接口隔离 |
| **容灾** | OSS 主存 + R2 每 15 分钟增量镜像（只增不删），徽章反映成败 |

---

## 8. 项目结构（实际）

```
Photo-Aiid-system/
├── frontend/                 # React + Vite 前端
│   └── src/components/        # Gallery / IndexTable / AdminPanel(投稿管理)
│                              # SubmitPanel(投稿) / AboutPage(使用教程) / Sidebar / Header
├── backend/                  # Python FastAPI 后端
│   ├── main.py               # 本地完整后端（画廊 + AI + 本地征稿）
│   ├── intake_server.py      # 云端精简后端入口（仅征稿，部署到服务器）
│   ├── intake.py             # 征稿路由（投稿码 / OSS 直传 / 看板 / 下钻 / 备份）
│   ├── database.py           # SQLite（多文件夹持久库 + 历史索引）
│   ├── engines/              # claude / zhipu / gemini / ollama / clip + prompt(共享提示词)
│   ├── services/             # scanner / analyzer / renamer / geocode / image_compat
│   ├── data/cn_districts.json# DataV 行政区划（离线反向地理编码）
│   └── requirements*.txt
├── src-tauri/                # 桌面应用外壳 (Tauri 2)
├── deploy/                   # 云端部署模板 (systemd service / nginx)
├── scripts/                  # 打包构建 + 云端运维
│   ├── build-mac.sh / build-win.ps1          # 桌面打包
│   ├── deploy-server.sh / setup-rclone.sh    # 部署征稿后端 / 装 rclone
│   ├── mirror-oss-to-r2.sh / install-r2-mirror.sh  # OSS→R2 持续镜像
│   └── archive-to-r2.sh / export-intake-meta.py
├── docs/                     # 使用教程、征稿/部署/下载文档、各版本发布说明
├── start.py                  # 一键启动（源码运行）
├── README.md
└── Photo-Aiid-system-技术规格书.md   # 本文档
```

---

## 9. 构建与发布

- **源码运行**：`python start.py` 自动装依赖、起前后端、开浏览器（http://localhost:5173）。
- **桌面打包**：
  - macOS（Apple Silicon）：本机 `bash scripts/build-mac.sh`（PyInstaller 冻结后端 + Tauri 套壳，产出 `.dmg`）。
  - Windows（x64）：推 `v*` tag 触发 GitHub Actions `build-windows.yml`，产出 `_x64-setup.exe`（NSIS）/ `.msi`。
  - 版本号需同步修改 `package.json` / `src-tauri/tauri.conf.json` 等多处；HEIC 依赖 `pillow-heif`。
- **云端征稿部署**：`scripts/deploy-server.sh` 一键部署 `intake_server` 到阿里云服务器（域名走 Cloudflare），rclone 镜像由 systemd timer 驱动。详见 `docs/部署到阿里云.md`、`docs/OSS接入配置.md`。

---

## 10. 版本路线图（已完成）

- **v1.x — 基础自动化**：Web + FastAPI + SQLite，文件夹挂载/递归扫描，多引擎识别，索引表 + CSV，模板化物理重命名，分析缓存。✅
- **v2.0 — 桌面化与多引擎**：Tauri 打包 Mac/Win，智谱/Gemini 接入，批量 EXIF/校正，离线反向地理编码。✅
- **v3.0 — 网页征稿与云端协作**：网页投稿 + STS 直传 OSS，App 远程投稿管理 + 看板下钻，OSS 主存 + R2 异地容灾，口令头鉴权。✅
- **v3.1 — 整理体验强化**：多文件夹持久库 + 历史索引（跨全库找图），原始文件名保留，HEIC/大图兼容，AI 二级类别「主类·子类」，提示词抽共享模块。✅ （当前 v3.1.4）

**后续展望（未实现）**：本地人脸聚类、OCR 入索引、真·向量检索（sqlite-vec 替代 LLM 语义匹配）、查重去重、AI 批量修图。

---

**文档说明：** 本规格书由 pemiamos 与 AI（Claude / Codex / AG 三方接力）协作维护，描述截至 v3.1.4 **已实现并发布**的系统。各版本详细变更见 `docs/release-v*.md`。
