import './AboutPage.css'

export default function AboutPage() {
  return (
    <section className="about-section">
      <div className="about-content">
        <h2>使用教程</h2>
        <p>
          Photo-Aiid-system 是一款 AI 照片管理工具：自动识别照片内容、批量重命名，
          还能<b>跨整个照片库一键找图</b>。如果你只是想把照片管好、随时找得到，先看下面这块👇
        </p>

        {/* 重点推荐：历史索引（面向普通用户） */}
        <div className="about-highlight">
          <h3>🕘 历史索引 —— 找照片，不用再记它在哪个文件夹</h3>
          <p>
            <b>这是最适合普通用户的功能。</b>照片平时散在一堆文件夹里，时间一长根本记不清
            「那张照片到底放哪了」。只要照片<b>曾经被本软件分析过</b>，它就会一直留在「历史档案」里——
            打开<b>「索引表」标签 → 点右上角「🕘 历史索引」</b>，输入关键词就能
            <b>跨所有文件夹</b>一次性搜出来。
          </p>
          <p>比如直接搜：</p>
          <ul>
            <li>「<b>南京</b>」「<b>日落</b>」「<b>外婆</b>」——按地点 / 标签 / 摄影师 / 文件名秒搜</li>
            <li>不想打字？搜索框下方有<b>最近搜过的词</b>和<b>整库最常见的标签</b>，点一下就搜</li>
            <li>结果像相册一样瀑布平铺，缩略图随用随取，<b>几万张照片也不卡</b></li>
          </ul>
          <p className="about-tip">
            💡 小贴士：从 v3.1 起，换文件夹<b>不会再清空</b>历史——你浏览、分析过的每个文件夹都会
            <b>累积进库</b>，用得越久、能搜的越多。要搜某批照片，记得先「浏览」并「分析」过它所在的文件夹。
          </p>
        </div>

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
          <li><b>历史索引</b> ⭐：跨所有分析过的文件夹一键找图——详见本页顶部的重点介绍。</li>
        </ol>

        <h2>3. 数据存放位置</h2>
        <p>数据库与缩略图缓存放在用户可写目录（不在 App 内部）：</p>
        <ul>
          <li>
            <b>macOS：</b><code>~/Library/Application Support/Photo-Aiid-system/</code>
          </li>
          <li>
            <b>Windows：</b><code>%APPDATA%\Photo-Aiid-system\</code>
          </li>
        </ul>
        <p>
          其中 <code>photo_aiid.db</code> 是索引与设置（含你填的 Key、以及历史索引的全部记录），
          <code>thumbnails/</code> 是缩略图缓存。<b>删除该文件夹</b>即可清空所有索引与设置（历史索引也会一并清空）；
          <b>复制该文件夹</b>即可备份或迁移到另一台电脑。
        </p>

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
