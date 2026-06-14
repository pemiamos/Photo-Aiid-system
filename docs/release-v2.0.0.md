# Photo-Aiid-system v2.0.0

AI 智能照片管理与批量处理系统 —— 桌面版正式发布（macOS / Apple Silicon）

## ✨ 这个版本带来了什么

- 🖥️ **桌面应用**：基于 Tauri 打包，双击即用，无需安装 Node.js / Python
- 📍 **地点识别优化**：有 GPS 时以 GPS 为准（精确到市/县），文件名中的地点信息仅作为细分补充，不再覆盖正确的 GPS 位置
- ⚠️ **失败原因可见**：分析失败的照片现在会显示具体失败原因（鼠标悬停查看）
- 📖 **全新使用教程**：内置「使用教程」页面，涵盖引擎配置（智谱 GLM / Claude / Gemini / Ollama）、使用流程、数据存放位置、常见问题
- 🏷️ 侧边栏新增版权信息（CC BY-NC-SA 4.0，星尘远征队 出品）

## 📦 下载与安装

下载 `Photo-Aiid-system_2.0.0_aarch64.dmg`，仅适用于 **Apple Silicon（M1/M2/M3/M4）Mac**。

1. 双击 `.dmg`，将 `Photo-Aiid-system.app` 拖入「应用程序」文件夹
2. **首次打开会被 macOS 拦截**（提示"无法验证开发者"或"已损坏，无法打开"）——这是因为本应用未经苹果签名，**不是病毒**
3. 解决方法（任选一种）：
   - **右键点击 App 图标 → 打开 → 在弹窗中再次点击「打开」**（只需一次，之后可正常双击）
   - 或在终端执行：
     ```bash
     xattr -dr com.apple.quarantine "/Applications/Photo-Aiid-system.app"
     ```

## 🔑 使用前准备

软件本身不含任何账号或密钥。首次打开后，在左侧栏「识别引擎」中选择一个 AI 引擎并填入对应 Key：

| 引擎 | 说明 |
|------|------|
| 智谱 GLM（推荐） | `glm-4v-flash` 免费，[获取 Key](https://open.bigmodel.cn/usercenter/apikeys) |
| Ollama | 完全本地免费，需先安装 [Ollama](https://ollama.com) 并下载视觉模型 |
| Claude / Gemini | 付费或有限免费额度，需各自官网获取 Key |

密钥仅保存在本机数据库，不会上传到任何第三方。

## 💾 数据存放位置

- `~/Library/Application Support/Photo-Aiid-system/photo_aiid.db` — 索引与设置
- `~/Library/Application Support/Photo-Aiid-system/thumbnails/` — 缩略图缓存

删除该文件夹即可清空所有数据；复制即可备份。

## ⚠️ 已知限制

- 当前仅提供 Apple Silicon 版本，Intel Mac 暂不支持
- 打包版未内置 CLIP 本地引擎，请使用智谱 / Gemini / Claude / Ollama
- 关闭窗口会完全退出应用并停止后台服务（设计行为，避免残留进程占用端口）
