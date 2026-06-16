import './AboutPage.css'

export default function AboutPage() {
  return (
    <section className="about-section">
      <div className="about-content">
        <h2>使用教程</h2>
        <p>AI 智能照片管理与批量处理系统。下面按「配置引擎 → 使用流程 → 常见问题」介绍。</p>

        <h2>1. 接入 AI 引擎（API Key）</h2>
        <p>
          软件本身不含任何账号或密钥，AI 识别需要你在<b>左侧栏「识别引擎」</b>选一个引擎并填入对应 Key。
          <b>密钥只保存在你本机，不会上传到第三方。</b>按需选一个即可：
        </p>
        <ul>
          <li>
            <b>🟢 智谱 GLM（推荐新手，有免费额度）：</b>默认模型 <code>glm-4v-flash</code> 视觉识别免费。
            到 <a href="https://open.bigmodel.cn/usercenter/apikeys" target="_blank" rel="noreferrer">open.bigmodel.cn</a> 获取
            形如 <code>xxxxxxxx.xxxxxxxx</code> 的 Key。
          </li>
          <li>
            <b>🔵 Claude（精度最高，付费）：</b>到 <a href="https://console.anthropic.com" target="_blank" rel="noreferrer">console.anthropic.com</a>
            获取形如 <code>sk-ant-…</code> 的 Key，需联网、按量计费。
          </li>
          <li>
            <b>🟡 Google Gemini（有免费额度）：</b>默认 <code>gemini-2.5-flash</code>。
            到 <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">aistudio.google.com/apikey</a>
            获取形如 <code>AIza…</code> 的 Key。
          </li>
          <li>
            <b>⚪ Ollama（完全本地、免 Key、隐私优先）：</b>需先装
            <a href="https://ollama.com" target="_blank" rel="noreferrer"> Ollama </a>
            并拉取视觉模型（如 <code>ollama pull gemma3:12b</code>）。Endpoint 默认
            <code>http://localhost:11434</code>，再选已安装的模型。照片不出本地。
          </li>
        </ul>
        <p>填完后点左侧栏底部「<b>测试连接</b>」，成功即可开始分析。</p>

        <h2>2. 使用流程</h2>
        <ol>
          <li><b>选择照片文件夹</b>：软件会递归扫描图片、提取 EXIF 并生成缩略图（不复制、不上传、不移动原图）。</li>
          <li><b>配置引擎</b>：见上一节，选引擎、填 Key、测试连接。</li>
          <li>
            <b>分析</b>：「全局分析」处理当前文件夹所有未分析的照片；
            「自选分析」先在画廊点选若干张，仅分析选中的（含强制重分析）。
          </li>
          <li><b>查看与校正</b>：分析后会出现标签、地点等信息，可人工校正。</li>
          <li><b>批量重命名</b>：用字段块（如 <code>[摄影师]_[地点]_[标签]</code>）拼出规则，预览无误后执行；自动去重、自动记日志。</li>
          <li><b>导出原图</b>：在画廊把缩略图<b>直接拖拽到桌面或文件夹</b>，即可复制出（重命名后的）原图。</li>
          <li><b>导出索引</b>：在「索引表」一键导出 CSV，Excel / Numbers 可直接打开。</li>
        </ol>

        <h2>3. 数据存放位置</h2>
        <p>数据库与缩略图缓存放在用户可写目录（不在 App 内部）：</p>
        <ul>
          <li><code>~/Library/Application Support/Photo-Aiid-system/photo_aiid.db</code> — 索引与设置（含你填的 Key）</li>
          <li><code>~/Library/Application Support/Photo-Aiid-system/thumbnails/</code> — 缩略图缓存</li>
        </ul>
        <p>删除该文件夹即可清空所有索引与设置；复制该文件夹即可备份。</p>

        <h2>4. 常见问题</h2>
        <ul>
          <li><b>窗口空白/转圈：</b>内置服务启动需 1～2 秒；若长时间空白，多为 8000 端口被占用，关掉占用程序后重开。</li>
          <li><b>提示"无法连接后端服务"：</b>通常是端口冲突或服务异常，完全退出（Cmd-Q）后重开。</li>
          <li><b>"API key not configured"：</b>当前引擎没填 Key 或填错，回左侧栏检查并测试连接。</li>
          <li><b>CLIP 引擎不可用：</b>打包版为控制体积未内置 CLIP，请改用智谱 / Gemini / Claude / Ollama。</li>
          <li><b>关窗即退出：</b>这是设计行为——关窗会完全退出并停止后台服务，避免残留进程占端口。</li>
        </ul>

        <h2>5. 发给别人时（双击报错）</h2>
        <p>
          若把本 App 发给他人，对方首次双击可能被 macOS 拦截（"无法验证开发者"/"已损坏"）。
          这不是病毒，而是未签名导致。让对方<b>右键点图标 → 打开 → 再点打开</b>即可（只需一次）；
          或在终端执行 <code>xattr -dr com.apple.quarantine "/Applications/Photo-Aiid-system.app"</code>。
        </p>

        <h2>6. 下载与平台（Mac / Windows）</h2>
        <p>
          本应用提供 <b>macOS（Apple Silicon）</b> 与 <b>Windows（x64）</b> 两个平台的安装包，
          均在 <a href="https://github.com/pemiamos/Photo-Aiid-system/releases" target="_blank" rel="noreferrer">GitHub Releases</a> 发布：
        </p>
        <ul>
          <li><b>macOS：</b>下载 <code>.dmg</code>，拖入「应用程序」即可（首次打开见上节绕过 Gatekeeper）。</li>
          <li>
            <b>Windows：</b>由 <b>GitHub Actions 自动构建</b>，在 Release 页下载
            <code>_x64-setup.exe</code>（NSIS 安装包，推荐）运行安装；另有 <code>.msi</code> 供企业部署。
            首次运行若被 SmartScreen 拦截，点「更多信息 → 仍要运行」即可（未签名所致，非病毒）。
          </li>
        </ul>
      </div>
    </section>
  )
}
