import './AboutPage.css'

export default function AboutPage() {
  return (
    <section className="about-section">
      <div className="about-content">
        <h2>v2.0 — Photo-Aiid-system</h2>
        <p>AI 智能照片管理与批量处理系统。Web 架构，Mac / Windows / Linux 通用。</p>

        <h2>核心功能</h2>
        <ul>
          <li><b>文件夹扫描：</b>输入文件夹路径，后端递归扫描所有图片文件（含子目录），自动提取 EXIF 元数据并生成缩略图。非侵入，不复制、不上传。</li>
          <li><b>AI 自动分类：</b>支持三种引擎——Claude Vision API（云端高精度）、Ollama 本地 LLM（隐私优先）、CLIP 本地推理（轻量快速）。用户可在左侧面板自由切换。</li>
          <li><b>批量重命名：</b>支持自定义模板（前缀_AI标签_日期_序号），可预览后执行物理重命名。自动去重，自动生成重命名日志。</li>
          <li><b>语义搜索：</b>用自然语言描述（如"海边日落时的合照"）搜索照片，AI 根据标签索引进行语义匹配。</li>
          <li><b>数据导出：</b>CSV 索引表一键导出，Excel / Numbers 可直接打开。</li>
        </ul>

        <h2>引擎配置说明</h2>
        <ul>
          <li><b>Claude API：</b>需要 API Key（<code>console.anthropic.com</code> 获取）。识别精度最高，需联网。Key 仅存于本机。</li>
          <li><b>Ollama 本地：</b>需安装 <a href="https://ollama.ai/" target="_blank" rel="noreferrer">Ollama</a> 并下载视觉模型（如 gemma3、llava）。完全离线，隐私安全。</li>
          <li><b>CLIP 本地：</b>需额外安装 <code>pip install sentence-transformers</code>。轻量分类，无需网络。</li>
        </ul>

        <h2>技术架构</h2>
        <ul>
          <li><b>前端：</b>React + Vite（本页面）</li>
          <li><b>后端：</b>Python FastAPI + SQLite</li>
          <li><b>API 文档：</b>启动后端后访问 <a href="http://localhost:8000/docs" target="_blank" rel="noreferrer">http://localhost:8000/docs</a></li>
        </ul>

        <h2>快速开始</h2>
        <ol>
          <li>启动后端：<code>cd backend && pip install -r requirements.txt && uvicorn main:app --reload</code></li>
          <li>启动前端：<code>cd frontend && npm install && npm run dev</code></li>
          <li>或一键启动：<code>python start.py</code></li>
        </ol>

        <h2>后续规划</h2>
        <ul>
          <li>向量语义检索（sqlite-vec 替代 LLM 匹配）</li>
          <li>人脸聚类与 OCR 文字识别</li>
          <li>AI 批量修图与查重去重</li>
          <li>可选 Tauri 桌面打包</li>
        </ul>
      </div>
    </section>
  )
}
