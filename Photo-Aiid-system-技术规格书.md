# Photo-Aiid-system · 技术规格书

> **AI 智能照片管理与批量处理系统**
> 版本：v2.0 · 统一架构版
> 日期：2026-06-13
> 作者：pemiamos × AI 协作

---

## 1. 项目愿景

开发一款**轻量级、隐私优先**的照片智能管理工具。用户通过浏览器即可使用——无需安装原生应用，**Mac 和 Windows 通用**。

核心能力：
- **AI 自动识别**照片内容，智能打标分类
- 基于原文件名 + AI 分析**生成关键词索引目录**
- 多维度**批量编辑**（EXIF、水印、重命名、分类）
- 支持**本地推理（隐私优先）** 或 **云端 API（精度优先）**，用户自由切换

---

## 2. 技术架构

### 2.1 架构总览

采用 **Web 前端 + 本地 Python 后端** 的混合架构，一套代码覆盖 Mac / Windows / Linux：

```
┌─────────────────────────────────────────────────────┐
│  浏览器 (Mac / Windows / Linux)                       │
│  前端: React + Vite                                  │
│  拖入照片 → 预览 → AI 分类 → 批量操作 → 导出           │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP REST API
┌──────────────────────▼──────────────────────────────┐
│  本地后端: Python (FastAPI)                           │
│                                                      │
│  ┌──────────────────┐    ┌────────────────────────┐  │
│  │ 本地推理引擎       │    │ 云端 API 引擎           │  │
│  │ · CLIP (ViT-B-32)│    │ · Claude Vision        │  │
│  │ · Ollama (本地LLM)│    │ · GPT-4o / Gemini      │  │
│  │ · ONNX Runtime   │    │ · 其他 Vision API       │  │
│  │ 免费、完全离线    │    │ 更强、需联网 + 费用     │  │
│  └──────────────────┘    └────────────────────────┘  │
│         ↑ 用户在设置中自由切换 ↑                       │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │ 数据层: SQLite + sqlite-vec (向量扩展)         │    │
│  │ · 元数据存储 · 向量检索 · 分析结果缓存          │    │
│  └──────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

### 2.2 技术栈

| 维度 | 技术选型 | 说明 |
|------|----------|------|
| **前端** | React + Vite | 现代化 UI，热更新，跨平台 |
| **后端** | Python + FastAPI | 异步高性能，AI 生态丰富 |
| **本地推理** | CLIP (ViT-B-32) + ONNX Runtime | 无 GPU 也能快速推理 |
| **本地 LLM** | Ollama (gemma3 / llava 等) | 可选的本地视觉大模型 |
| **云端 API** | Claude Vision / GPT-4o | 高精度识别，需 API Key |
| **数据库** | SQLite + sqlite-vec | 轻量、零配置、支持向量检索 |
| **图像处理** | Pillow / OpenCV | 缩略图生成、EXIF 提取 |
| **部署** | 一键启动脚本 | `python start.py` 即启动前后端 |

### 2.3 为什么选择 Web 而不是原生 App

| 对比维度 | SwiftUI (原方案 A) | Electron (原方案 B) | **Web + Python (当前方案)** |
|----------|-------------------|--------------------|-----------------------------|
| 跨平台 | ❌ 仅 macOS | ✅ 但安装包 150MB+ | ✅ 浏览器即用 |
| AI 生态 | Apple Vision 有限 | 需桥接 Python | ✅ Python 原生 |
| 安装成本 | App Store | 800MB+ 安装包 | `pip install` + 浏览器 |
| 开发效率 | Swift 生态较小 | 复杂度高 | ✅ 前后端解耦，迭代快 |
| 未来扩展 | 锁死 Apple | 重度框架 | 可套壳为桌面 App (Tauri) |

---

## 3. 核心数据模型

```
PhotoAsset
├── id: UUID
├── fileName: String          # 原文件名
├── filePath: String          # 本地完整路径
├── relativePath: String      # 相对于挂载根的路径
├── fileSize: Int64
├── createdAt: DateTime
├── exifData: EXIFInfo
│   ├── dateTimeOriginal: DateTime?
│   ├── cameraModel: String?
│   ├── lensModel: String?
│   ├── fNumber: Float?
│   ├── iso: Int?
│   ├── focalLength: Float?
│   ├── gpsLatitude: Float?
│   └── gpsLongitude: Float?
├── aiResult: AIAnalysis
│   ├── category: String      # 主类别 (自然风光/人像/美食/...)
│   ├── tags: [String]        # 3-6 个标签
│   ├── description: String   # 简短画面描述
│   ├── slug: String          # 英文短名 (用于文件名)
│   ├── embedding: Vector?    # 512维向量 (用于语义检索)
│   ├── engine: String        # 使用的引擎标识
│   └── analyzedAt: DateTime
├── suggestedName: String     # 模板生成的新文件名
├── isRenamed: Boolean        # 是否已物理重命名
└── scanStatus: Enum          # queued / analyzing / done / error

Project
├── id: UUID
├── name: String
├── rootPath: String          # 挂载的文件夹根路径
├── photos: [PhotoAsset]
├── createdAt: DateTime
└── lastScanAt: DateTime

Tag
├── id: UUID
├── name: String
├── category: Enum            # 主题/场景/人物/地点/器材
├── source: Enum              # AI / Manual / FileName
└── count: Int                # 关联照片数
```

---

## 4. 核心功能模块

### A. 智能扫描与挂载 (Non-destructive Sync)

- **非侵入式链接：** 应用不拷贝原始文件，仅读取路径和元数据
- **增量监控：** 支持 watchdog 实时监控文件夹变化，自动分析新照片
- **EXIF 提取：** 自动提取拍摄日期、相机型号、镜头参数、GPS 坐标
- **递归扫描：** 支持子目录递归，排除 `.` 开头的隐藏目录

### B. AI 识别引擎 (Vision Engine)

**双模式架构——用户自由切换：**

| 模式 | 引擎 | 特点 | 适用场景 |
|------|------|------|----------|
| 本地推理 | CLIP (ViT-B-32) via ONNX | 免费、离线、隐私安全 | 日常分类、批量处理 |
| 本地推理 | Ollama (gemma3/llava) | 免费、离线、更智能 | 需要描述性分析 |
| 云端 API | Claude Vision | 高精度、需网络 | 复杂场景、高质量标注 |
| 云端 API | GPT-4o / Gemini | 高精度、需网络 | 备选云端引擎 |

**识别策略：**
- 使用英文 Prompt 推理以确保高精度，前端显示中文标签
- 将图片转换为向量 (Vector Embedding)，存入 SQLite 向量库
- 综合利用文件名、文件夹路径中的人工线索辅助分类

**分类标签体系：**

```python
CATEGORIES = {
    "自然风光": "a photo of natural scenery, mountains, sea, or sky",
    "人像":     "a portrait of a person, people, or human faces",
    "宠物动物": "a photo of a cat, dog, bird, or other animals",
    "美食图片": "a photo of delicious food, drinks, or meals",
    "城市建筑": "a photo of city buildings, streets, or architecture",
    "电子截图": "a screenshot of a website or computer software",
    "文档表格": "a photo of a document, paper with text, or table",
    "街拍":     "a candid street photo of daily life scenes",
}
```

### C. 自动化索引与重命名 (Batch Engine)

- **动态索引表：** 实时生成包含 "原文件名 · AI标签 · 拍摄日期 · 建议新名" 的索引目录
- **批量重命名模板：** 用户自定义，如 `[前缀]_[AI标签]_[日期]_[序号].jpg`
- **物理重命名：** 直接改写磁盘文件名（Chrome/Edge 下通过 File System Access API）
- **ZIP 副本模式：** 不支持 FSAPI 的浏览器自动回退为下载重命名后的 ZIP 包
- **重命名日志：** 每次物理重命名自动导出 CSV 日志（旧名 → 新名），可追溯
- **影子目录：** 支持在不移动原文件的前提下，创建基于标签的虚拟文件夹结构

### D. 语义检索系统 (Search & Retrieval)

- **关键词过滤：** 按标签、日期、器材、文件大小实时筛选
- **自然语言搜索：** 用户输入描述性词汇（如 "海边日落时的合照"）进行语义检索
- **向量检索 (正式版)：** 使用 CLIP embedding + sqlite-vec 实现真正的语义匹配
- **LLM 辅助匹配 (过渡方案)：** 将标签索引发送给 LLM 做语义匹配

### E. 数据导出

- **CSV 索引表导出：** Excel/Numbers 可直接打开
- **ZIP 副本下载：** 打包重命名后的文件副本
- **JSON 元数据导出：** 供程序化处理

---

## 5. API 设计 (后端接口)

```
POST   /api/scan           # 挂载文件夹，开始扫描
GET    /api/photos          # 获取照片列表 (支持分页/过滤)
GET    /api/photos/:id      # 获取单张照片详情
POST   /api/analyze         # 触发 AI 分析 (可选 engine 参数)
POST   /api/analyze/:id     # 重新分析单张照片
POST   /api/rename          # 执行批量重命名
GET    /api/search?q=       # 关键词搜索
POST   /api/search/semantic # 语义搜索 (向量检索)
GET    /api/export/csv      # 导出 CSV
GET    /api/export/json     # 导出 JSON
GET    /api/tags            # 获取所有标签
PUT    /api/settings        # 更新引擎设置
GET    /api/settings        # 获取当前设置
GET    /api/health          # 健康检查 + 引擎状态
```

---

## 6. UI 设计

### 布局结构

```
┌─────────────────────────────────────────────────────────────┐
│  Photo-Aiid-system                              [v2.0] [👤] │
├─────────────────────────────────────────────────────────────┤
│ ┌─────────┐ ┌─────────────────────────────────────────────┐ │
│ │ 挂载照片 │ │  🔍 搜索 / 语义搜索                         │ │
│ │         │ ├─────────────────────────────────────────────┤ │
│ │ 识别引擎 │ │  [ 画廊 ]  [ 索引表 ]  [ 说明 ]             │ │
│ │ ·Claude  │ │                                             │ │
│ │ ·Ollama  │ │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐          │ │
│ │ ·CLIP    │ │  │ img │ │ img │ │ img │ │ img │          │ │
│ │         │ │  │ tag │ │ tag │ │ tag │ │ tag │          │ │
│ │ 重命名   │ │  └─────┘ └─────┘ └─────┘ └─────┘          │ │
│ │ 模板配置 │ │                                             │ │
│ │         │ │  [⚡ AI Auto-tag]  [✏️ Batch]  [📥 Export] │ │
│ │ 标签过滤 │ │                                             │ │
│ │ 🏔️ 风景 │ ├─────────────────────────────────────────────┤ │
│ │ 👤 人像 │ │  Photo Detail / Batch Edit Panel             │ │
│ │ 🍽️ 美食 │ │                                             │ │
│ │         │ └─────────────────────────────────────────────┘ │
│ │ 库统计   │                                                │
│ └─────────┘                                                │
└─────────────────────────────────────────────────────────────┘
```

### 设计风格

- **暗色主题**为主（摄影师友好），支持亮色切换
- 琥珀色 (Amber) 作为品牌色 / 强调色
- 等宽字体 (JetBrains Mono) 用于元数据展示
- 胶片边框风格的卡片设计
- 瀑布流 (Masonry) 画廊布局

---

## 7. Demo 验证成果

当前已有两个 HTML 原型验证了核心功能的可行性：

### v0.3 Demo (`AI-Photo-Index-Demo.html`)
- ✅ 拖入照片 + Claude/Ollama 双引擎识别
- ✅ EXIF 提取 + 标签过滤 + 语义搜索
- ✅ 模板化重命名 + CSV/ZIP 导出

### v0.4 正式版 (`AI-Photo-Index.html`)
- ✅ File System Access API 挂载文件夹（含子目录递归）
- ✅ **真·物理重命名**（直接改写磁盘文件名）
- ✅ IndexedDB 分析结果缓存（刷新秒级恢复）
- ✅ 文件名/文件夹名作为 AI 分析上下文
- ✅ 重命名日志 CSV 自动导出
- ✅ API Key 本地加密存储

### Demo 验证的关键结论
1. **英文 Prompt 必须**：AI 识别必须使用英文推理中介，克服模型中文偏差
2. **缓存机制关键**：首次分析慢，但结果按 "路径+大小+修改时间" 缓存后秒级恢复
3. **UI 布局已验证**："左侧设置面板 + 顶部 Tab + 瀑布流画廊" 体验最佳

---

## 8. 版本路线图 (Roadmap)

### V1.0 — 基础自动化 (MVP)
- [ ] Web 前端 (React + Vite) 基础框架
- [ ] FastAPI 后端 + SQLite 数据库
- [ ] 文件夹挂载与递归扫描
- [ ] CLIP 本地推理 + Claude API 双引擎
- [ ] 全自动识别分类 + 标签体系
- [ ] 动态索引表 + CSV 导出
- [ ] 模板化批量重命名（物理 + ZIP）
- [ ] 分析结果缓存与增量更新

### V1.5 — 语义增强
- [ ] sqlite-vec 向量检索（替代 LLM 匹配）
- [ ] 影子目录（基于标签的虚拟文件夹导出）
- [ ] 更多云端引擎接入 (GPT-4o / Gemini)
- [ ] 批量 EXIF 编辑

### V2.0 — 深度智能
- [ ] 本地人脸聚类：识别特定人物并自动聚合
- [ ] OCR 文字识别：路牌、文档内容入索引
- [ ] 私密相册：本地加密隐藏
- [ ] 多文件夹项目管理

### V3.0 — 智能编辑
- [ ] AI 批量修图（自动光影调整）
- [ ] 查重与去重（内容相似度检测）
- [ ] 语义搜索增强（接入本地 LLaVA 等更强模型）
- [ ] 可选 Tauri 桌面打包（一键安装）

---

## 9. 性能与隐私规范

| 维度 | 要求 |
|------|------|
| **隐私** | 默认本地推理模式，所有图片处理在用户本机完成；云端 API 为可选项，需用户主动开启 |
| **API Key 安全** | 仅存储在用户本机浏览器 localStorage / 后端环境变量，不传输到第三方 |
| **性能 - 扫描** | 10,000 张照片文件夹挂载 < 30 秒 |
| **性能 - 推理** | CLIP 本地推理 < 200ms/张 (CPU)；云端 API < 3s/张 |
| **性能 - 检索** | 向量语义搜索 < 500ms (10 万张库) |
| **内存** | 使用流式读取 + 分页加载 (Lazy Loading)，内存占用 < 500MB |
| **缓存** | 分析结果按 "路径 + 大小 + 修改时间" 持久化，避免重复推理 |
| **模型体积** | CLIP ViT-B-32 ONNX 约 350MB，首次启动后台静默下载 |

---

## 10. 开发环境搭建

### 前端
```bash
cd frontend
npm install
npm run dev          # 启动开发服务器 (默认 localhost:5173)
```

### 后端
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload          # 启动 API 服务 (默认 localhost:8000)
```

### 一键启动
```bash
python start.py      # 同时启动前后端，自动打开浏览器
```

---

## 11. 项目结构（规划）

```
Photo-Aiid-system/
├── frontend/                    # React + Vite 前端
│   ├── src/
│   │   ├── components/          # UI 组件
│   │   │   ├── Gallery.jsx      # 瀑布流画廊
│   │   │   ├── IndexTable.jsx   # 索引表格
│   │   │   ├── Sidebar.jsx      # 侧边栏控制面板
│   │   │   ├── PhotoCard.jsx    # 照片卡片
│   │   │   └── SearchBar.jsx    # 搜索栏
│   │   ├── services/            # API 调用层
│   │   ├── stores/              # 状态管理
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── package.json
│   └── vite.config.js
├── backend/                     # Python FastAPI 后端
│   ├── main.py                  # FastAPI 入口
│   ├── engines/                 # AI 引擎封装
│   │   ├── clip_engine.py       # CLIP 本地推理
│   │   ├── ollama_engine.py     # Ollama 本地 LLM
│   │   └── cloud_engine.py      # 云端 API (Claude/GPT)
│   ├── services/                # 业务逻辑
│   │   ├── scanner.py           # 文件扫描
│   │   ├── analyzer.py          # AI 分析调度
│   │   ├── renamer.py           # 批量重命名
│   │   └── search.py            # 搜索与检索
│   ├── models/                  # 数据模型
│   ├── database.py              # SQLite + 向量库
│   └── requirements.txt
├── docs/                        # 文档归档
│   ├── design-v1.md             # 原设计文档 (归档)
│   ├── demo-guide.md            # Demo 部署教程 (归档)
│   └── spec-v1.md               # 原技术规格书 (归档)
├── prototypes/                  # HTML 原型 (归档)
│   ├── v0.3-demo.html
│   └── v0.4-full.html
├── start.py                     # 一键启动脚本
├── Photo-Aiid-system-技术规格书.md  # 本文档
└── README.md
```

---

## 附录：与旧文档的对应关系

本文档统一整合了以下三份旧文档：

| 旧文档 | 内容 | 本文档对应章节 |
|--------|------|---------------|
| AI 照片自动分类工具 - 设计文档.md | 产品设计、数据模型、UI 线框 | §3, §4, §6 |
| AI 照片自动分类工具 Demo 部署教程.md | Python Demo 搭建指南 | §7, §10 |
| AI 照片自动分类工具-技术规格书.md | 功能需求、技术栈、路线图 | §2, §4, §8, §9 |

**关键变更：**
- 技术路线从 SwiftUI / Electron 统一为 **Web (React + Vite) + Python (FastAPI)**
- AI 引擎从单一方案统一为**混合模式**（本地 CLIP / Ollama + 云端 API 可切换）
- 产品名称统一为 **Photo-Aiid-system**

---

**文档说明：** 本规格书由 pemiamos 与 AI 协作制定。HTML 原型（v0.3 / v0.4）已验证核心功能可行。后续开发基于此规格书推进。
