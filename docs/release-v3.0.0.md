# Photo-Aiid-system v3.0.0

AI 照片管理 + 网页征稿协作系统 —— 从「单机整理」迈向「本地整理 + 云端征稿」（macOS / Apple Silicon）

## ✨ 这个版本带来了什么

v2.0 是一台单机 AI 照片整理工具；**v3.0 在保留全部本地能力的基础上，长出了一整套网页征稿与云端协作链路**：

### 🌐 网页征稿（摄影师侧，零安装）
- 摄影师凭**投稿码**打开专属链接即可上传，手机/电脑浏览器直接用，无需安装软件
- 照片**浏览器直传阿里云 OSS**（STS 临时凭证，限定到本人目录），不经过服务器，上百人也扛得住
- 可选填写标注，归入标签便于后期搜索

### 🗂️ 云端投稿管理（编辑侧，收进 App）
- App 新增「投稿管理」标签，填**服务器地址 + 管理口令**即可远程管理云端征稿
- 书籍项目管理（建/重命名/归档）、投稿码管理（单个/批量生成、专属链接、**二维码**、CSV 导出）
- **征稿看板**：已交/未交统计、按投稿码**下钻看缩略图墙 + 放大查看**、搜索 / 筛选 / 排序、**一键复制未交催稿名单/链接**、自动刷新与更新时间
- App 内统一弹窗替代浏览器原生弹窗，成功提示走独立 toast 通道

### ☁️ 双云存储与异地备份
- **阿里云 OSS** 长期主存（国内读写快，App 看图始终走 OSS 预签名）
- **Cloudflare R2** 持续备份：云端服务器每 15 分钟自动增量镜像（systemd timer，只增不删），徽章实时反映「持续备份中 / 备份异常」
- 编辑可优先从 R2（下行流量免费）下载选图

### 🔐 部署与安全
- 精简云端后端 `intake_server.py`，只暴露征稿接口，无画廊/照片接口，天然隔离
- 远程管理用 `X-Intake-Admin-Token` 口令头鉴权
- 一键部署脚本（systemd + nginx + certbot HTTPS）、rclone 装配与 R2 镜像安装脚本，文档齐全

> 本地照片整理（AI 识别、批量重命名、语义搜索、离线地理编码、拖拽到桌面等）**全部保留**，使用方式不变。

## 📦 下载与安装

提供 **macOS（Apple Silicon）** 与 **Windows（x64）** 两个平台，按需下载。

### macOS（Apple Silicon M1/M2/M3/M4）
下载 `Photo-Aiid-system_3.0.0_aarch64.dmg`：

1. 双击 `.dmg`，将 `Photo-Aiid-system.app` 拖入「应用程序」文件夹
2. **首次打开会被 macOS 拦截**（提示"无法验证开发者"或"已损坏，无法打开"）——这是因为本应用未经苹果签名，**不是病毒**
3. 解决方法（任选一种）：
   - **右键点击 App 图标 → 打开 → 在弹窗中再次点击「打开」**（只需一次，之后可正常双击）
   - 或在终端执行：
     ```bash
     xattr -dr com.apple.quarantine "/Applications/Photo-Aiid-system.app"
     ```

### Windows（x64）
由 **GitHub Actions 自动构建**。下载 `Photo-Aiid-system_3.0.0_x64-setup.exe`（NSIS 安装包，推荐）运行安装；另提供 `Photo-Aiid-system_3.0.0_x64_zh-CN.msi` 供企业部署。首次运行若被 SmartScreen 拦截，点「更多信息 → 仍要运行」即可（未签名所致，非病毒）。

## 🔑 使用前准备

- **本地整理**：在左侧栏「识别引擎」选一个 AI 引擎并填入 Key（智谱 GLM `glm-4v-flash` 免费推荐；Ollama 完全本地免费；Claude / Gemini 需各自 Key）。密钥仅存本机。
- **网页征稿**（可选）：需自行部署征稿后端 + 配置阿里云 OSS / Cloudflare R2，见 `docs/部署到阿里云.md`、`docs/OSS接入配置.md`、`docs/征稿工作流程.md`。不用征稿功能可忽略。

## 💾 数据存放位置

- `~/Library/Application Support/Photo-Aiid-system/photo_aiid.db` — 本地索引与设置
- `~/Library/Application Support/Photo-Aiid-system/thumbnails/` — 缩略图缓存
- 征稿数据在云端服务器（OSS 主存 + R2 备份），本机 App 仅远程管理

删除该文件夹即可清空本地数据；复制即可备份。

## ⚠️ 已知限制

- App 未经苹果签名，首次打开需手动绕过 Gatekeeper（见上）
- 网页征稿为可选高级功能，依赖自有服务器与云存储账号，需按文档自行部署
- R2 为大陆访问较慢的境外存储，仅作**不读取**的异地备份；日常读取/下载请走 OSS 或服务器侧镜像

## 📄 License

CC BY-NC-SA 4.0 · 星尘远征队 出品
