这是一份专门为你整理的 **AI 照片自动分类工具 Demo 部署教程**。你可以将其保存为 `.md` 文件，或者直接根据这个指南在任何电脑上重新搭建环境。

---

# 📸 Photo-Aiid-system：Demo 部署与运行指南

本教程旨在帮助用户在本地快速搭建一个基于 AI 的照片自动分类与索引原型系统。该系统使用 **OpenAI CLIP 模型**，无需上传照片到云端，保护隐私且支持语义识别。

---

## 一、 环境准备 (Preparation)

### 1. 安装 Python
*   **Windows 用户**：前往 [python.org](https://www.python.org/) 下载安装包。**安装时必须勾选 "Add Python to PATH"**。
*   **Mac 用户**：通常系统自带，但建议前往官网安装最新版，以确保 `python3` 和 `pip3` 可用。

### 2. 检查安装是否成功
打开终端（Windows 的 **CMD** 或 Mac 的 **Terminal**），输入以下命令并回车：
```bash
python --version
# 或者
python3 --version
```
如果显示 `Python 3.x.x`，说明安装成功。

---

## 二、 核心命令 (Command Line)

请在终端中依次执行以下命令来安装必要的 AI 运行库。

### 1. 安装必要的库 (Libraries)
**Windows 用户使用：**
```bash
pip install streamlit pillow sentence-transformers pandas numpy
```

**Mac 用户使用（推荐）：**
```bash
python3 -m pip install streamlit pillow sentence-transformers pandas numpy
```
*注：如果下载速度慢，可以在命令末尾加上 `-i https://pypi.tuna.tsinghua.edu.cn/simple` 使用镜像加速。*

---

## 三、 创建代码文件 (Script Setup)

1.  在桌面新建一个文件夹，命名为 `AI_Photo_Project`。
2.  打开文本编辑器（Mac 用“文本编辑”并切换为“纯文本”；Windows 用“记事本”）。
3.  将以下经过优化的代码粘贴进去，并保存为 **`my_ai_app.py`**。

```python
import streamlit as st
import os
from PIL import Image
from PIL.ExifTags import TAGS
from sentence_transformers import SentenceTransformer
import numpy as np
import pandas as pd

# 设置网页布局
st.set_page_config(page_title="Photo-Aiid-system", layout="wide")

# 1. 加载 AI 模型
@st.cache_resource
def get_model():
    return SentenceTransformer('clip-ViT-B-32')

model = get_model()

# 2. 定义 AI 识别逻辑 (中英映射增强准确率)
CAT_MAP = {
    "a photo of natural scenery, mountains, sea, or sky": "自然风光",
    "a portrait of a person, people, or human faces": "人像",
    "a photo of a cat, dog, bird, or other animals": "宠物动物",
    "a photo of delicious food, drinks, or meals": "美食图片",
    "a photo of city buildings, streets, or architecture": "城市建筑",
    "a screenshot of a website or computer software": "电子截图",
    "a photo of a document, paper with text, or table": "文档表格"
}
ENGLISH_PROMPTS = list(CAT_MAP.keys())
CHINESE_LABELS = list(CAT_MAP.values())

# 3. 提取拍摄日期函数
def get_exif_date(img):
    try:
        exif = img._getexif()
        if exif:
            for tag, value in exif.items():
                tag_name = TAGS.get(tag, tag)
                if tag_name == 'DateTimeOriginal':
                    return value.split(' ')[0].replace(':', '')
    except: pass
    return "未知日期"

# --- GUI 界面设计 ---
st.sidebar.header("⚙️ Photo-Aiid-system 控制面板")
folder_path = st.sidebar.text_input("照片文件夹路径")
prefix = st.sidebar.text_input("重命名前缀", "AI归档")
process_btn = st.sidebar.button("开始全自动分析", type="primary")

st.title("📂 智能照片批量命名与索引")

if process_btn and folder_path:
    if not os.path.exists(folder_path):
        st.error("❌ 路径不存在，请检查后重试！")
    else:
        files = [f for f in os.listdir(folder_path) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
        my_bar = st.progress(0, text="AI 正在分析内容...")
        
        text_emb = model.encode(ENGLISH_PROMPTS)
        data_list = []
        
        for i, f in enumerate(files):
            img_path = os.path.join(folder_path, f)
            try:
                img = Image.open(img_path)
                # AI 推理
                img_emb = model.encode(img)
                scores = np.dot(text_emb, img_emb)
                category = CHINESE_LABELS[np.argmax(scores)]
                # 日期提取
                date_str = get_exif_date(img)
                # 拟定新名
                new_name = f"{prefix}_{category}_{date_str}_{f}"
                
                data_list.append({"原文件名": f, "AI分类": category, "日期": date_str, "新文件名预览": new_name, "path": img_path})
            except: pass
            my_bar.progress((i + 1) / len(files))

        df = pd.DataFrame(data_list)
        st.success(f"✅ 处理完成！已完成 {len(files)} 张照片的语义索引。")
        
        # 结果展示区
        t1, t2 = st.tabs(["📝 索引清单", "🖼️ 分类画廊"])
        with t1:
            st.dataframe(df[["原文件名", "AI分类", "日期", "新文件名预览"]], use_container_width=True)
            csv = df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 导出索引表格 (Excel可打开)", csv, "index.csv", "text/csv")
        with t2:
            for cat in df["AI分类"].unique():
                st.subheader(f"分类：{cat}")
                cols = st.columns(4)
                sub_df = df[df["AI分类"] == cat]
                for j, row in enumerate(sub_df.itertuples()):
                    with cols[j % 4]:
                        st.image(row.path, use_container_width=True)
                        st.caption(row.新文件名预览)
else:
    st.info("👈 请在左侧侧边栏输入照片文件夹路径并点击开始。")
```

---

## 四、 启动与运行 (Execution)

### 1. 启动命令
在终端里，先进入代码所在的文件夹，或者直接输入以下通用命令：

**Windows:**
```bash
streamlit run my_ai_app.py
```

**Mac (最推荐写法):**
```bash
python3 -m streamlit run ~/Desktop/AI_Photo_Project/my_ai_app.py
```

### 2. 第一次运行说明
*   **下载模型**：首次点击“开始分析”时，终端会显示下载进度。模型大小约 **600MB**，根据网速需要 1-3 分钟。
*   **浏览器弹出**：运行成功后，系统会自动打开浏览器窗口（通常是 `http://localhost:8501`）。

### 3. 如何获取文件夹路径
*   **Mac 用户**：右键点击文件夹 -> 按住 **Option (⌥)** 键 -> 选择 **“将...拷贝为路径名称”** -> 在程序中粘贴。
*   **Windows 用户**：点击文件夹顶部地址栏 -> 复制路径 -> 在程序中粘贴。

---

## 五、 常见问题排除 (Troubleshooting)

| 现象 | 原因 | 解决方法 |
| :--- | :--- | :--- |
| `command not found: pip` | 路径未设置 | 在 Mac 上尝试用 `python3 -m pip`。 |
| 网页一直是白屏 | 模型正在下载 | 查看终端窗口的百分比进度，下载完会自动显示。 |
| 分类不准确 | 语义理解偏差 | 尝试修改代码中的 `CAT_MAP` 字典，使用更精准的英文描述。 |
| 无法读取日期 | 照片无 EXIF | 很多从社交软件下载的照片会丢失原图元数据，这是正常现象。 |

---

## 六、 给 Antigravity 开发团队的提示
如果您是该项目的后续开发者，请注意：
1.  **推理加速**：生产环境建议将 `CLIP` 部署在 **ONNX Runtime** 上以提升在 CPU 上的扫描速度。
2.  **持久化**：目前数据仅保存在 Session 中，正式版需对接 **SQLite**。
3.  **并发处理**：批量处理 1000+ 照片时需引入 `ThreadPoolExecutor` 防止 UI 假死。