# Photo-Aiid-system

> AI 智能照片管理与批量处理系统

[![License](https://img.shields.io/badge/license-MIT-blue.svg)]()
[![Python](https://img.shields.io/badge/python-3.10+-green.svg)]()
[![React](https://img.shields.io/badge/react-18+-61dafb.svg)]()

---

## ✨ 功能亮点

- 🤖 **AI 自动识别** — 拖入照片即可智能分类打标，现已支持 **Gemini 强 JSON 模式** 与安全校验
- 🔀 **多引擎切换** — 本地 CLIP / Ollama (隐私优先) 或 云端 Claude API / Gemini API (精度优先)
- 🚀 **极速增量扫描** — **共享 SQLite 长连接** + **$O(1)$ 内存缓存过滤** + **多核并发**，二次扫描达毫秒级
- 📁 **批量重命名** — 模板化命名 + 物理重命名 + 日志追溯
- 🖱️ **拖拽与原生选择** — 拖拽文件夹/文件自动解析父路径，或点击“浏览”唤起系统原生选择对话框（AppleScript/PowerShell）
- 🔄 **分析进度轮询** — 后台异步 AI 分析，前端每秒轮询，照片属性与统计数据在画廊中**实时动态弹现**
- 🧹 **历史自动重置** — 导入新文件夹时，自动物理擦除数据库历史记录（级联删除），并重置前端搜索、标签过滤状态
- 🔍 **语义搜索** — 用自然语言描述找照片
- 📊 **索引导出** — CSV / JSON 一键导出
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
│   ├── engines/           # AI 引擎 (CLIP / Ollama / Claude)
│   ├── services/          # 业务逻辑 (扫描 / 分析 / 重命名)
│   └── main.py            # API 入口
├── docs/                  # 历史文档归档
├── start.py               # 一键启动脚本
└── README.md
```

---

## 🔧 AI 引擎配置

| 引擎 | 类型 | 说明 |
|------|------|------|
| **CLIP** | 本地 | 免费、离线、快速分类。需额外安装 `pip install sentence-transformers` |
| **Ollama** | 本地 | 免费、离线、高质量描述。需安装 [Ollama](https://ollama.ai/) 并下载视觉模型 |
| **Claude** | 云端 | 最高精度，需 API Key。[获取 Key](https://console.anthropic.com/) |

---

## 📝 API 文档

启动后端后访问 http://localhost:8000/docs 查看交互式 API 文档。

---

## 📄 License

MIT
