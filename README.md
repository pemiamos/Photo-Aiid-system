# Photo-Aiid-system

> AI 智能照片管理与批量处理系统

[![License](https://img.shields.io/badge/license-MIT-blue.svg)]()
[![Python](https://img.shields.io/badge/python-3.10+-green.svg)]()
[![React](https://img.shields.io/badge/react-18+-61dafb.svg)]()

---

## ✨ 功能亮点

- 🤖 **AI 自动识别** — 拖入照片即可智能分类、打标、提取摄影师与拍摄地点，强 JSON 模式 + 安全校验
- 🔀 **四引擎切换** — 本地 Ollama / CLIP（隐私优先）或云端 **智谱 GLM（glm-4v-flash 免费）** / Claude / Gemini
- 👤 **摄影师识别** — 从文件名/文件夹提取摄影师（含昵称、网名、拼音），结构化入库，可用于命名
- 📍 **拍摄地点** — 有 GPS 时**离线反向地理编码**到中文市/县级（内置 3238 条行政区划数据，不联网）；无 GPS 时由 AI 结合文件名/相邻序列/画面地标推断
- 🏷️ **EXIF 提取** — 相机/镜头/光圈/快门/ISO/日期；无拍摄时间自动回退文件生成时间
- ✏️ **人工校正** — 分析完成后可**单张或批量**修改标签与地点
- 📁 **可视化重命名** — **拖拽式模板构建器**（[摄影师]/[地点]/[类别]/[标签]/[日期]/[相机] 自由组合）+ 实时预览 + 空字段智能省略 + 物理重命名 + CSV 日志
- ⏱️ **分析控制** — 实时计时 + 预计剩余时间 + **暂停/继续**
- 🚀 **极速增量扫描** — 共享 SQLite 长连接 + 内存缓存过滤 + 多核并发，二次扫描达毫秒级
- 🖱️ **拖拽与原生选择** — 拖拽文件夹/文件自动解析父路径，或点击“浏览”唤起系统原生选择对话框（AppleScript/PowerShell）
- 🔄 **实时进度** — 后台异步分析，前端每秒轮询，照片属性在画廊中**逐张动态弹现**
- 🧹 **历史自动重置** — 切换文件夹时自动清理旧记录并重置搜索/过滤/选择状态
- 🔍 **语义搜索** — 用自然语言描述找照片
- 📊 **索引导出** — CSV 一键导出（含摄影师/地点/EXIF）
- 🌓 **暗色主题** — 摄影师友好的专业暗色 UI
- 💻 **跨平台** — Mac / Windows / Linux 浏览器通用

---

## 🚀 快速开始

### 前置要求

- [Node.js](https://nodejs.org/) 18+
- [Python](https://python.org/) 3.10+

### 一键启动

```bash
python start.py
```

脚本会自动安装依赖、启动前后端服务、打开浏览器。

### 手动启动

**后端:**
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

**前端:**
```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:5173

---

## 🏗️ 项目结构

```
Photo-Aiid-system/
├── frontend/              # React + Vite 前端
├── backend/               # Python FastAPI 后端
│   ├── engines/           # AI 引擎 (zhipu / claude / gemini / ollama / clip)
│   ├── services/          # 业务逻辑 (扫描 / 分析 / 重命名 / 离线地理编码)
│   ├── data/              # 中国行政区划数据 (离线反向地理编码)
│   └── main.py            # API 入口
├── docs/                  # 历史文档归档
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

> 默认引擎为 **Ollama 本地**；所有引擎共用同一识别链路（摄影师/地点/EXIF/相邻序列上下文）。

---

## 📝 API 文档

启动后端后访问 http://localhost:8000/docs 查看交互式 API 文档。

---

## 📄 License

MIT
