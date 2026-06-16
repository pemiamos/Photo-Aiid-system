import { useEffect, useState, useCallback, useMemo, useRef, createContext, useContext } from 'react'
import QRCode from 'qrcode'
import { usePhotoDispatch, Actions } from '../stores/photoStore'
import * as api from '../services/api'
import './AdminPanel.css'

/* ── App 内弹窗（替代 window.confirm/prompt，统一风格、可定制）──
   用法：const dialog = useDialog()
        await dialog.confirm({ title, message, confirmText, danger })  → true/false
        await dialog.prompt({ title, message, defaultValue, confirmText }) → string|null */
const DialogContext = createContext(null)
export function useDialog() { return useContext(DialogContext) }

function DialogProvider({ children }) {
  const [dlg, setDlg] = useState(null)   // {type,title,message,confirmText,danger,defaultValue}
  const resolver = useRef(null)

  const settle = useCallback((result) => {
    setDlg(null)
    const r = resolver.current
    resolver.current = null
    r?.(result)
  }, [])

  const confirm = useCallback((opts = {}) => new Promise(res => {
    resolver.current = res
    setDlg({ type: 'confirm', confirmText: '确定', ...opts })
  }), [])

  const prompt = useCallback((opts = {}) => new Promise(res => {
    resolver.current = res
    setDlg({ type: 'prompt', confirmText: '保存', defaultValue: '', ...opts })
  }), [])

  return (
    <DialogContext.Provider value={{ confirm, prompt }}>
      {children}
      {dlg && (
        <DialogModal
          dlg={dlg}
          onCancel={() => settle(dlg.type === 'prompt' ? null : false)}
          onConfirm={(val) => settle(dlg.type === 'prompt' ? val : true)}
        />
      )}
    </DialogContext.Provider>
  )
}

function DialogModal({ dlg, onCancel, onConfirm }) {
  const [val, setVal] = useState(dlg.defaultValue || '')
  const inputRef = useRef(null)

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onCancel() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onCancel])

  useEffect(() => {
    if (dlg.type === 'prompt' && inputRef.current) {
      inputRef.current.focus(); inputRef.current.select()
    }
  }, [dlg.type])

  function ok() {
    if (dlg.type === 'prompt') {
      const t = val.trim()
      if (!t) return            // 空值不提交
      onConfirm(t)
    } else {
      onConfirm(true)
    }
  }

  return (
    <div className="lightbox" onClick={onCancel}>
      <div className="dialog-card" onClick={e => e.stopPropagation()}>
        <div className="dialog-title">{dlg.title}</div>
        {dlg.message && <div className="dialog-msg">{dlg.message}</div>}
        {dlg.type === 'prompt' && (
          <input
            ref={inputRef}
            className="dialog-input"
            value={val}
            onChange={e => setVal(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') ok() }}
          />
        )}
        <div className="dialog-actions">
          <button className="abtn ghost sm" onClick={onCancel}>取消</button>
          <button
            className={`abtn ${dlg.danger ? 'danger' : 'primary'} sm`}
            onClick={ok}
          >{dlg.confirmText}</button>
        </div>
      </div>
    </div>
  )
}

// 投稿管理：远程连接征稿服务器（可部署在阿里云，见 docs/部署到阿里云.md），
// 把书籍项目 / 征稿看板 / 投稿码管理收进 App。一台服务器可承接多本书籍，
// 新建在前、旧的往下排列。鉴权用「服务器地址 + 管理口令」（口令走请求头）。
export default function AdminPanel() {
  const dispatch = usePhotoDispatch()
  const fail = useCallback((msg) => {
    dispatch({ type: Actions.SET_ERROR, payload: msg })
  }, [dispatch])

  const saved = api.getIntakeServer()
  const [connected, setConnected] = useState(null)   // null=探测中 true/false
  const [base, setBase] = useState(saved.base || '')
  const [token, setToken] = useState(saved.token || '')
  const [connecting, setConnecting] = useState(false)
  const [msg, setMsg] = useState('')

  // 进入时若已存过地址+口令，自动验一次
  const probe = useCallback(async () => {
    const s = api.getIntakeServer()
    if (!s.token) { setConnected(false); return }
    try {
      await api.intakePing()
      setConnected(true)
    } catch {
      setConnected(false)
    }
  }, [])

  useEffect(() => { probe() }, [probe])

  async function connect(e) {
    e?.preventDefault()
    setMsg(''); setConnecting(true)
    api.setIntakeServer({ base, token })
    try {
      await api.intakePing()
      setConnected(true)
    } catch (err) {
      setConnected(false)
      setMsg(err.message || '连接失败')
    } finally {
      setConnecting(false)
    }
  }

  function disconnect() {
    api.setIntakeServer({ base: '', token: '' })
    setBase(''); setToken(''); setConnected(false)
  }

  if (connected === null) {
    return <div className="admin-wrap center"><div className="admin-empty">连接征稿服务器…</div></div>
  }

  if (!connected) {
    return (
      <div className="admin-wrap center">
        <form className="admin-login" onSubmit={connect}>
          <h2>连接征稿服务器</h2>
          <p className="admin-login-hint">
            填入征稿服务器地址与管理口令。本机调试可填 <code>http://127.0.0.1:8000</code>；
            公网部署见「部署到阿里云」教程。
          </p>
          <input
            value={base}
            onChange={e => setBase(e.target.value)}
            placeholder="服务器地址，如 https://intake.你的域名.com"
            spellCheck={false}
            autoFocus
          />
          <input
            type="password"
            value={token}
            onChange={e => setToken(e.target.value)}
            placeholder="管理口令"
          />
          <button type="submit" className="abtn primary block" disabled={connecting}>
            {connecting ? '连接中…' : '连接'}
          </button>
          {msg && <div className="admin-login-err">{msg}</div>}
        </form>
      </div>
    )
  }

  return (
    <DialogProvider>
      <Console fail={fail} onDisconnect={disconnect} />
    </DialogProvider>
  )
}

/* ── 已连接主控制台 ── */
function Console({ fail, onDisconnect }) {
  const dialog = useDialog()
  const [books, setBooks] = useState(null)
  const [selected, setSelected] = useState('')   // 选中书籍 code
  const [view, setView] = useState('board')       // board | codes
  const [showNew, setShowNew] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [ossMode, setOssMode] = useState('')      // oss | local
  const [toast, setToast] = useState('')          // 成功提示（独立于错误通道）

  // 成功类轻提示：不再复用错误通道，2.4s 自动消失
  const toastTimer = useRef(null)
  const notify = useCallback((msg) => {
    setToast(msg)
    if (toastTimer.current) clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(''), 2400)
  }, [])
  useEffect(() => () => { if (toastTimer.current) clearTimeout(toastTimer.current) }, [])

  const loadBooks = useCallback(async (keep) => {
    try {
      const data = await api.intakeBooks()
      setBooks(data.rows)
      setSelected(prev => {
        const want = keep || prev
        if (want && data.rows.some(b => b.code === want)) return want
        return data.rows[0]?.code || ''
      })
    } catch (e) {
      fail(e.message)
    }
  }, [fail])

  useEffect(() => { loadBooks() }, [loadBooks])
  useEffect(() => {
    api.intakeOssConfig().then(d => setOssMode(d.mode)).catch(() => {})
  }, [])

  async function createBook() {
    const title = newTitle.trim()
    if (!title) return
    try {
      const res = await api.intakeCreateBook({ title })
      setNewTitle(''); setShowNew(false)
      await loadBooks(res.code)
      setView('codes')
    } catch (e) { fail(e.message) }
  }

  async function toggleArchive(b) {
    const next = b.status === 'archived' ? 'active' : 'archived'
    if (next === 'archived' && !(await dialog.confirm({
      title: '归档书籍',
      message: `归档《${b.title}》？归档后不再征稿，但数据保留。`,
      confirmText: '归档',
    }))) return
    try {
      await api.intakeSetBookStatus(b.code, next)
      await loadBooks()
    } catch (e) { fail(e.message) }
  }

  async function rename(b) {
    const title = await dialog.prompt({
      title: '重命名书籍',
      defaultValue: b.title,
    })
    if (title == null || title === b.title) return
    try {
      await api.intakeRenameBook(b.code, title)
      await loadBooks()
    } catch (e) { fail(e.message) }
  }

  const current = books?.find(b => b.code === selected)
  const serverBase = api.getIntakeServer().base || window.location.origin

  return (
    <div className="admin-wrap">
      <div className="admin-top">
        <h2 className="admin-title">投稿管理</h2>
        <span className="server-chip" title={serverBase}>
          <i className="dot ok" /> {serverBase}
        </span>
        <button className="abtn ghost sm" onClick={onDisconnect}>断开连接</button>
      </div>

      <div className="admin-grid">
        {/* 左：书籍项目列表 */}
        <aside className="book-list">
          <div className="book-list-head">
            <span>书籍项目</span>
            <button className="abtn primary sm" onClick={() => setShowNew(v => !v)}>
              {showNew ? '取消' : '＋ 新建'}
            </button>
          </div>

          {showNew && (
            <div className="book-new">
              <input
                value={newTitle}
                onChange={e => setNewTitle(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && createBook()}
                placeholder="书籍名称，如「沿江2026」"
                autoFocus
              />
              <button className="abtn primary sm block" onClick={createBook}>创建</button>
            </div>
          )}

          {books == null
            ? <div className="admin-empty sm">加载中…</div>
            : books.length === 0
              ? <div className="admin-empty sm">还没有书籍，点「＋ 新建」开始</div>
              : books.map(b => (
                <div
                  key={b.code}
                  className={`book-card${b.code === selected ? ' active' : ''}${b.status === 'archived' ? ' archived' : ''}`}
                  onClick={() => setSelected(b.code)}
                >
                  <div className="book-card-top">
                    <span className="book-name">{b.title}</span>
                    {b.status === 'archived' && <span className="badge muted">已归档</span>}
                  </div>
                  <div className="book-meta">
                    <span className="mono">{b.code}</span>
                    <span>· {b.created}</span>
                  </div>
                  <div className="book-stats">
                    {b.people} 人 · 已交 <b className="ok">{b.submitted}</b> · {b.files} 张 · {b.mb} MB
                  </div>
                  <div className="book-actions" onClick={e => e.stopPropagation()}>
                    <button className="btn-link" onClick={() => rename(b)}>重命名</button>
                    <button className="btn-link" onClick={() => toggleArchive(b)}>
                      {b.status === 'archived' ? '恢复' : '归档'}
                    </button>
                  </div>
                </div>
              ))}
        </aside>

        {/* 右：选中书籍详情 */}
        <section className="book-detail">
          {!current ? (
            <div className="admin-empty">从左侧选择或新建一本书籍</div>
          ) : (
            <>
              <div className="detail-head">
                <div className="detail-title">
                  <b>{current.title}</b>
                  <span className="mono detail-code">{current.code}</span>
                  {current.status === 'archived' && <span className="badge muted">已归档</span>}
                </div>
              </div>

              <IntakeAddress book={current.code} base={serverBase} ossMode={ossMode} fail={fail} notify={notify} />

              <div className="seg seg-detail">
                <button className={view === 'board' ? 'active' : ''} onClick={() => setView('board')}>征稿看板</button>
                <button className={view === 'codes' ? 'active' : ''} onClick={() => setView('codes')}>投稿码管理</button>
              </div>

              {view === 'board'
                ? <Board book={current.code} base={serverBase} fail={fail} notify={notify} />
                : <Codes book={current.code} base={serverBase} fail={fail} notify={notify} onChanged={() => loadBooks(current.code)} />}
            </>
          )}
        </section>
      </div>

      {toast && <div className="admin-toast" role="status">{toast}</div>}
    </div>
  )
}

/* ── 复制小工具 ── */
async function copyText(text, label, fail) {
  try {
    await navigator.clipboard.writeText(text)
    fail(`已复制${label ? '：' + label : ''}`)
  } catch {
    window.prompt('手动复制', text)
  }
}

function intakeUrl(base, code) {
  const b = (base || '').replace(/\/+$/, '')
  return code ? `${b}/intake?code=${encodeURIComponent(code)}` : `${b}/intake`
}

/* ── 投稿地址面板（整本书共用，提到书籍头部）── */
function IntakeAddress({ book, base, ossMode, fail, notify }) {
  const dialog = useDialog()
  const webEntry = intakeUrl(base)
  const [arch, setArch] = useState(null)   // 归档状态 {running,last_at_str,ok,message,rclone,log_tail}
  const pollRef = useRef(null)

  const loadStatus = useCallback(async () => {
    try {
      const s = await api.intakeArchiveStatus(book)
      setArch(s)
      return s
    } catch { return null }
  }, [book])

  // 切换书籍时拉一次状态，并清掉旧轮询
  useEffect(() => {
    loadStatus()
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [loadStatus])

  // 进行中则每 4s 轮询，结束自动停
  useEffect(() => {
    if (arch?.running && !pollRef.current) {
      pollRef.current = setInterval(async () => {
        const s = await loadStatus()
        if (s && !s.running) {
          clearInterval(pollRef.current); pollRef.current = null
          notify?.(s.ok ? `《${book}》归档完成` : `归档失败：${s.message || ''}`)
        }
      }, 4000)
    }
  }, [arch?.running, book, loadStatus, notify])

  async function startArchive() {
    if (!(await dialog.confirm({
      title: 'R2 归档',
      message: `把《${book}》的原图从阿里云 OSS 归档到 Cloudflare R2？该操作在服务器后台执行，可能耗时较久。`,
      confirmText: '开始归档',
    }))) return
    try {
      await api.intakeArchive(book)
      notify?.('已开始归档，进度将自动刷新')
      await loadStatus()
    } catch (e) { fail(e.message) }
  }

  const running = arch?.running
  const r2Tone = running ? 'warn' : (arch?.ok === false ? 'warn' : (arch?.last_at_str ? 'ok' : ''))
  const r2Text = running
    ? '归档进行中…'
    : arch?.last_at_str
      ? `上次归档 ${arch.last_at_str}${arch.ok === false ? '（失败）' : ''}`
      : '尚未归档'

  return (
    <div className="intake-addr">
      <div className="intake-addr-main">
        <div className="intake-addr-label">投稿地址</div>
        <code className="intake-addr-url" title={webEntry}>{webEntry}</code>
        <button className="abtn primary sm" onClick={() => copyText(webEntry, '网页投稿入口', notify)}>复制网页入口</button>
        <button className="abtn ghost sm" onClick={() => copyText(base, 'App 服务器地址', notify)}>复制 App 服务器地址</button>
      </div>
      <div className="pipeline">
        <span className="pl-badge ok"><i className="dot ok" />征稿服务器 已连接</span>
        <span className={`pl-badge ${ossMode === 'oss' ? 'ok' : 'warn'}`}>
          <i className={`dot ${ossMode === 'oss' ? 'ok' : 'warn'}`} />
          阿里云 OSS {ossMode === 'oss' ? '已联动直传' : ossMode === 'local' ? '本地直存' : '检测中…'}
        </span>
        <span className={`pl-badge ${r2Tone}`} title={arch?.log_tail || ''}>
          <i className={`dot ${r2Tone || 'muted'}`} />R2 归档 · {r2Text}
          {arch && arch.rclone === false
            ? <span className="muted" style={{ marginLeft: 6 }}>（服务器未装 rclone）</span>
            : <button className="btn-link copy" onClick={startArchive} disabled={running}
                style={{ marginLeft: 6 }}>{running ? '进行中' : '一键归档'}</button>}
        </span>
      </div>
    </div>
  )
}

/* ── 征稿看板 ── */
const BOARD_AUTO_MS = 15000

function Board({ book, base, fail, notify }) {
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [updated, setUpdated] = useState(null)     // 最后更新时间戳
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')      // all | submitted | pending
  const [sort, setSort] = useState({ key: 'code', dir: 1 })
  const [auto, setAuto] = useState(false)
  const [open, setOpen] = useState(null)           // 展开下钻的投稿码
  const autoRef = useRef(null)

  const load = useCallback(async (silent) => {
    if (!silent) setBusy(true)
    try {
      setData(await api.intakeBoard(book))
      setUpdated(Date.now())
    } catch (e) {
      fail(e.message)
    } finally {
      setBusy(false)
    }
  }, [book, fail])

  // 切换书籍：重载并收起下钻
  useEffect(() => { setOpen(null); load() }, [load])

  // 自动刷新（静默，不打断展开）
  useEffect(() => {
    if (auto) {
      autoRef.current = setInterval(() => load(true), BOARD_AUTO_MS)
      return () => clearInterval(autoRef.current)
    }
  }, [auto, load])

  const rows = useMemo(() => {
    if (!data) return []
    const q = query.trim().toLowerCase()
    let rs = data.rows.filter(r => {
      if (filter === 'submitted' && !r.submitted) return false
      if (filter === 'pending' && r.submitted) return false
      if (q && !(`${r.code} ${r.name}`.toLowerCase().includes(q))) return false
      return true
    })
    const { key, dir } = sort
    rs = [...rs].sort((a, b) => {
      let av = a[key], bv = b[key]
      if (key === 'code' || key === 'name') { av = String(av || ''); bv = String(bv || '') ; return av.localeCompare(bv) * dir }
      return ((av || 0) - (bv || 0)) * dir
    })
    return rs
  }, [data, query, filter, sort])

  function toggleSort(key) {
    setSort(s => s.key === key ? { key, dir: -s.dir } : { key, dir: key === 'code' || key === 'name' ? 1 : -1 })
  }
  const arrow = (key) => sort.key === key ? (sort.dir > 0 ? ' ▲' : ' ▼') : ''

  // 未交名单一键复制（催稿用）
  function copyPending() {
    const list = (data?.rows || []).filter(r => !r.submitted)
    if (!list.length) { notify?.('没有未交的摄影师'); return }
    const text = list.map(r => `${r.code} ${r.name}`).join('\n')
    copyText(text, `${list.length} 位未交名单`, notify)
  }
  function copyPendingLinks() {
    const list = (data?.rows || []).filter(r => !r.submitted)
    if (!list.length) { notify?.('没有未交的摄影师'); return }
    const text = list.map(r => `${r.name}：${intakeUrl(base, r.code)}`).join('\n')
    copyText(text, `${list.length} 条未交投稿链接`, notify)
  }

  if (!data) return <div className="admin-empty">{busy ? '加载中…' : '暂无数据'}</div>

  const pending = data.total_photographers - data.submitted

  return (
    <div className="admin-body">
      <div className="stat-cards">
        <Stat label="摄影师" value={data.total_photographers} />
        <Stat label="已交" value={data.submitted} tone="ok" />
        <Stat label="未交" value={pending} tone={pending ? 'warn' : ''} />
        <Stat label="收稿张数" value={data.total_files} />
        <Stat label="占用容量" value={`${data.total_mb} MB`} />
        <span className="board-updated">
          {updated ? `更新于 ${new Date(updated).toLocaleTimeString('zh-CN', { hour12: false })}` : ''}
        </span>
        <label className="board-auto">
          <input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} />自动刷新
        </label>
        <button className="abtn ghost sm" onClick={() => load()} disabled={busy}>刷新</button>
      </div>

      <div className="board-toolbar">
        <input
          className="board-search"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="搜索投稿码 / 姓名"
        />
        <div className="seg board-filter">
          {[['all', '全部'], ['submitted', '已交'], ['pending', '未交']].map(([k, t]) => (
            <button key={k} className={filter === k ? 'active' : ''} onClick={() => setFilter(k)}>{t}</button>
          ))}
        </div>
        <span className="form-spacer" />
        {pending > 0 && (
          <>
            <button className="abtn ghost sm" onClick={copyPending}>复制未交名单</button>
            <button className="abtn ghost sm" onClick={copyPendingLinks}>复制未交链接</button>
          </>
        )}
      </div>

      <table className="admin-table board-table">
        <thead>
          <tr>
            <th className="sortable" onClick={() => toggleSort('code')}>投稿码{arrow('code')}</th>
            <th className="sortable" onClick={() => toggleSort('name')}>姓名{arrow('name')}</th>
            <th>状态</th>
            <th className="sortable" onClick={() => toggleSort('files')}>张数{arrow('files')}</th>
            <th className="sortable" onClick={() => toggleSort('mb')}>大小{arrow('mb')}</th>
            <th>标注分布</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => {
            const expandable = r.files > 0
            const isOpen = open === r.code
            return (
              <FragmentRow key={r.code}>
                <tr
                  className={`${r.submitted ? '' : 'row-pending'}${expandable ? ' row-clickable' : ''}${isOpen ? ' row-open' : ''}`}
                  onClick={() => expandable && setOpen(isOpen ? null : r.code)}
                >
                  <td className="mono">
                    {expandable && <span className="row-caret">{isOpen ? '▾' : '▸'}</span>}
                    {r.code}
                  </td>
                  <td>{r.name}</td>
                  <td>{r.submitted
                    ? <span className="badge ok">已交</span>
                    : <span className="badge pending">未交</span>}</td>
                  <td>{r.files}</td>
                  <td>{r.mb} MB</td>
                  <td className="admin-labels">
                    {(r.labels || []).filter(l => l.label).map(l => (
                      <span key={l.label} className="chip">{l.label}·{l.count}</span>
                    ))}
                    {(!r.labels || r.labels.filter(l => l.label).length === 0) && <span className="muted">—</span>}
                  </td>
                </tr>
                {isOpen && (
                  <tr className="row-detail">
                    <td colSpan={6}>
                      <FileGrid code={r.code} name={r.name} fail={fail} />
                    </td>
                  </tr>
                )}
              </FragmentRow>
            )
          })}
          {rows.length === 0 && (
            <tr><td colSpan={6} className="muted" style={{ textAlign: 'center', padding: '24px' }}>
              {data.rows.length === 0 ? '本书还没有投稿码，去「投稿码管理」新增' : '没有匹配的结果'}
            </td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

// <tbody> 不允许 Fragment 直接包多个 <tr>？实则允许 key 的 Fragment。封装便于阅读。
function FragmentRow({ children }) {
  return <>{children}</>
}

/* ── 下钻：某摄影师的照片缩略图墙（懒加载 + 点击放大）── */
function FileGrid({ code, name, fail }) {
  const [state, setState] = useState({ loading: true, files: null })
  const [lightbox, setLightbox] = useState(null)   // 当前放大的 index

  useEffect(() => {
    let alive = true
    setState({ loading: true, files: null })
    api.intakeFiles(code)
      .then(d => { if (alive) setState({ loading: false, files: d.files }) })
      .catch(e => { if (alive) { setState({ loading: false, files: [] }); fail(e.message) } })
    return () => { alive = false }
  }, [code, fail])

  if (state.loading) return <div className="grid-empty">载入照片…</div>
  const files = state.files || []
  if (!files.length) return <div className="grid-empty">该摄影师暂无照片</div>

  return (
    <>
      <div className="file-grid">
        {files.map((f, i) => (
          <button key={f.id} className="thumb" onClick={() => setLightbox(i)} title={`${f.file_name}${f.label ? ' · ' + f.label : ''}`}>
            <img src={api.intakeImageSrc(f.url)} alt={f.file_name} loading="lazy" />
            {f.label && f.label !== '未命名' && <span className="thumb-label">{f.label}</span>}
          </button>
        ))}
      </div>
      {lightbox != null && (
        <Lightbox
          files={files}
          index={lightbox}
          name={name}
          onClose={() => setLightbox(null)}
          onNav={d => setLightbox(i => (i + d + files.length) % files.length)}
        />
      )}
    </>
  )
}

/* ── 放大查看（带左右切换、元数据）── */
function Lightbox({ files, index, name, onClose, onNav }) {
  const f = files[index]
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowLeft') onNav(-1)
      else if (e.key === 'ArrowRight') onNav(1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, onNav])

  return (
    <div className="lightbox" onClick={onClose}>
      <div className="lb-stage" onClick={e => e.stopPropagation()}>
        <button className="lb-nav prev" onClick={() => onNav(-1)} aria-label="上一张">‹</button>
        <img src={api.intakeImageSrc(f.url)} alt={f.file_name} />
        <button className="lb-nav next" onClick={() => onNav(1)} aria-label="下一张">›</button>
        <div className="lb-info">
          <span className="lb-name">{name} · {f.file_name}</span>
          <span className="lb-meta">
            {index + 1}/{files.length}
            {f.label && f.label !== '未命名' ? ` · ${f.label}` : ''}
            {f.location ? ` · ${f.location}` : ''}
            {f.mb ? ` · ${f.mb} MB` : ''}
            {f.date ? ` · ${f.date}` : ''}
          </span>
        </div>
        <button className="lb-close" onClick={onClose} aria-label="关闭">✕</button>
      </div>
    </div>
  )
}

function Stat({ label, value, tone = '' }) {
  return (
    <div className="stat-card">
      <div className={`stat-value ${tone}`}>{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  )
}

/* ── 投稿码管理 ── */
function Codes({ book, base, fail, notify, onChanged }) {
  const dialog = useDialog()
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [name, setName] = useState('')
  const [contact, setContact] = useState('')
  const [code, setCode] = useState('')
  const [batch, setBatch] = useState('')
  const [showBatch, setShowBatch] = useState(false)
  const [query, setQuery] = useState('')
  const [qr, setQr] = useState(null)               // {name, url} 正在展示二维码的摄影师

  const load = useCallback(async () => {
    setBusy(true)
    try {
      setData(await api.intakeCodes(book))
    } catch (e) {
      fail(e.message)
    } finally {
      setBusy(false)
    }
  }, [book, fail])

  useEffect(() => { load() }, [load])

  async function addOne(e) {
    e.preventDefault()
    if (!name.trim()) return
    try {
      await api.intakeCreateCode({ name: name.trim(), contact: contact.trim(), code: code.trim(), book })
      setName(''); setContact(''); setCode('')
      await load(); onChanged?.()
    } catch (err) { fail(err.message) }
  }

  async function addBatch() {
    if (!batch.trim()) return
    try {
      const res = await api.intakeCreateCodesBatch(batch, book)
      setBatch(''); setShowBatch(false)
      await load(); onChanged?.()
      if (res.created) notify?.(`已生成 ${res.created.length} 个投稿码`)
    } catch (err) { fail(err.message) }
  }

  async function remove(r) {
    if (r.files > 0) { fail('该摄影师已有投稿，不能删除'); return }
    if (!(await dialog.confirm({
      title: '删除投稿码',
      message: `删除投稿码 ${r.code}（${r.name}）？此操作不可恢复。`,
      confirmText: '删除',
      danger: true,
    }))) return
    try {
      await api.intakeDeleteCode(r.id)
      await load(); onChanged?.()
    } catch (err) { fail(err.message) }
  }

  async function exportCsv() {
    try {
      await api.intakeExportCsv({ book, base })
    } catch (err) { fail(err.message) }
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return data?.rows || []
    return (data?.rows || []).filter(r =>
      `${r.code} ${r.name} ${r.contact || ''}`.toLowerCase().includes(q))
  }, [data, query])

  return (
    <div className="admin-body">
      <form className="admin-form" onSubmit={addOne}>
        <input value={name} onChange={e => setName(e.target.value)} placeholder="姓名（必填）" />
        <input value={contact} onChange={e => setContact(e.target.value)} placeholder="联系方式（选填）" />
        <input value={code} onChange={e => setCode(e.target.value)} placeholder="指定投稿码（留空自动）" className="mono" />
        <button type="submit" className="abtn primary sm">新增</button>
        <button type="button" className="abtn ghost sm" onClick={() => setShowBatch(v => !v)}>
          {showBatch ? '收起批量' : '批量生成'}
        </button>
        <span className="form-spacer" />
        <button type="button" className="abtn ghost sm" onClick={load} disabled={busy}>刷新</button>
      </form>

      {showBatch && (
        <div className="admin-batch">
          <textarea
            value={batch}
            onChange={e => setBatch(e.target.value)}
            placeholder="每行一个姓名，自动分配连续投稿码"
            rows={5}
          />
          <button className="abtn primary sm" onClick={addBatch}>批量生成</button>
        </div>
      )}

      <div className="codes-bar">
        <input
          className="board-search"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="搜索投稿码 / 姓名 / 联系方式"
        />
        <span className="codes-count muted">共 {filtered.length} / {data?.rows?.length || 0} 个</span>
        <span className="form-spacer" />
        <button className="abtn ghost sm" onClick={exportCsv}>↓ 导出全部投稿码</button>
      </div>

      <table className="admin-table">
        <thead>
          <tr><th>投稿码</th><th>姓名</th><th>联系方式</th><th>状态</th><th>专属投稿链接</th><th></th></tr>
        </thead>
        <tbody>
          {filtered.map(r => (
            <tr key={r.id}>
              <td className="mono">{r.code}</td>
              <td>{r.name}</td>
              <td className="muted">{r.contact || '—'}</td>
              <td>{r.submitted
                ? <span className="badge ok">已交 {r.files}</span>
                : <span className="badge pending">未交</span>}</td>
              <td className="codes-link-cell">
                <button
                  className="btn-link copy"
                  onClick={() => copyText(intakeUrl(base, r.code), `${r.name} 的投稿链接`, notify)}
                  title={intakeUrl(base, r.code)}
                >复制链接</button>
                <button
                  className="btn-link copy"
                  onClick={() => setQr({ name: r.name, url: intakeUrl(base, r.code) })}
                >二维码</button>
              </td>
              <td>
                <button
                  className="btn-link del"
                  onClick={() => remove(r)}
                  disabled={r.files > 0}
                  title={r.files > 0 ? '已有投稿，不能删除' : '删除'}
                >删除</button>
              </td>
            </tr>
          ))}
          {filtered.length === 0 && (
            <tr><td colSpan={6} className="muted" style={{ textAlign: 'center', padding: '24px' }}>
              {(data?.rows || []).length === 0 ? '还没有投稿码，用上方表单新增' : '没有匹配的结果'}
            </td></tr>
          )}
        </tbody>
      </table>

      {qr && <QrModal name={qr.name} url={qr.url} onClose={() => setQr(null)} notify={notify} />}
    </div>
  )
}

/* ── 二维码弹窗（摄影师扫码直达专属投稿页）── */
function QrModal({ name, url, onClose, notify }) {
  const [src, setSrc] = useState('')

  useEffect(() => {
    QRCode.toDataURL(url, { width: 320, margin: 1, errorCorrectionLevel: 'M' })
      .then(setSrc)
      .catch(() => setSrc(''))
  }, [url])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  function download() {
    if (!src) return
    const a = document.createElement('a')
    a.href = src
    a.download = `投稿二维码_${name || ''}.png`
    a.click()
  }

  return (
    <div className="lightbox" onClick={onClose}>
      <div className="qr-card" onClick={e => e.stopPropagation()}>
        <div className="qr-title">{name} · 扫码投稿</div>
        {src
          ? <img className="qr-img" src={src} alt="投稿二维码" />
          : <div className="grid-empty">生成中…</div>}
        <div className="qr-url" title={url}>{url}</div>
        <div className="qr-actions">
          <button className="abtn ghost sm" onClick={() => copyText(url, '投稿链接', notify)}>复制链接</button>
          <button className="abtn primary sm" onClick={download}>下载二维码</button>
        </div>
        <button className="lb-close" onClick={onClose} aria-label="关闭">✕</button>
      </div>
    </div>
  )
}
