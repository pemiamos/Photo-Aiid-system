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

/* 书籍项目的自定义排序持久化在本地（按服务器地址分桶）。后端按 created_at 返回，
   这里把用户拖拽出的顺序覆盖上去；未在记录里的书（新建的）排到末尾、保持原相对序。 */
function _orderKey(base) { return 'intake_book_order:' + (base || '') }
function _loadOrder(base) {
  try { return JSON.parse(localStorage.getItem(_orderKey(base))) || [] } catch { return [] }
}
function _saveOrder(base, codes) {
  try { localStorage.setItem(_orderKey(base), JSON.stringify(codes)) } catch { /* 忽略 */ }
}
/* 记住上次选中的书目（按服务器地址分桶），下次打开投稿管理自动回到同一本。 */
function _selKey(base) { return 'intake_book_selected:' + (base || '') }
function _loadSel(base) {
  try { return localStorage.getItem(_selKey(base)) || '' } catch { return '' }
}
function _saveSel(base, code) {
  try { localStorage.setItem(_selKey(base), code || '') } catch { /* 忽略 */ }
}
function _applyOrder(rows, order) {
  if (!order || !order.length) return rows
  const idx = c => { const i = order.indexOf(c); return i === -1 ? Infinity : i }
  return [...rows].sort((a, b) => idx(a.code) - idx(b.code))
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
  const [dragCode, setDragCode] = useState(null)  // 正在拖拽的书籍 code

  // 成功类轻提示：不再复用错误通道，2.4s 自动消失
  const toastTimer = useRef(null)
  const notify = useCallback((msg) => {
    setToast(msg)
    if (toastTimer.current) clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(''), 2400)
  }, [])
  useEffect(() => () => { if (toastTimer.current) clearTimeout(toastTimer.current) }, [])

  const orderBase = api.getIntakeServer().base || window.location.origin

  const loadBooks = useCallback(async (keep) => {
    try {
      const data = await api.intakeBooks()
      setBooks(_applyOrder(data.rows, _loadOrder(orderBase)))
      setSelected(prev => {
        // 优先级：显式 keep > 当前选中 > 上次记住的 > 列表第一本
        const want = keep || prev || _loadSel(orderBase)
        if (want && data.rows.some(b => b.code === want)) return want
        return data.rows[0]?.code || ''
      })
    } catch (e) {
      fail(e.message)
    }
  }, [fail, orderBase])

  useEffect(() => { loadBooks() }, [loadBooks])

  // 选中书目变化即持久化，下次打开恢复到同一本
  useEffect(() => { if (selected) _saveSel(orderBase, selected) }, [selected, orderBase])

  /* ── 拖拽排序（基于鼠标指针，不用 HTML5 draggable）──
     原因：Tauri 打包后 webview 接管 OS 级拖放，会吞掉页面内 HTML5 拖拽事件，
     导致 draggable 在桌面 App 里失效。改用 mousedown/mousemove/mouseup 自己实现，
     浏览器与桌面 App 都能拖；拖过即实时换位，松手持久化到本地。 */
  const dragRef = useRef({ active: false, code: null, moved: false, startY: 0 })
  const suppressClickRef = useRef(false)

  const onDocMouseMove = useCallback((e) => {
    const st = dragRef.current
    if (!st.active) return
    if (!st.moved && Math.abs(e.clientY - st.startY) < 5) return  // 阈值：区分点击与拖拽
    if (!st.moved) { st.moved = true; setDragCode(st.code) }
    e.preventDefault()
    const el = document.elementFromPoint(e.clientX, e.clientY)
    const overCode = el?.closest('.book-card')?.getAttribute('data-code')
    if (!overCode || overCode === st.code) return
    setBooks(prev => {
      const from = prev.findIndex(b => b.code === st.code)
      const to = prev.findIndex(b => b.code === overCode)
      if (from === -1 || to === -1 || from === to) return prev
      const next = [...prev]
      const [moved] = next.splice(from, 1)
      next.splice(to, 0, moved)
      return next
    })
  }, [])

  const onDocMouseUp = useCallback(() => {
    const st = dragRef.current
    window.removeEventListener('mousemove', onDocMouseMove)
    window.removeEventListener('mouseup', onDocMouseUp)
    if (st.moved) {
      const base = api.getIntakeServer().base || window.location.origin
      setBooks(prev => { _saveOrder(base, prev.map(b => b.code)); return prev })
      suppressClickRef.current = true  // 拖拽后抑制随之而来的 click 选中
    }
    dragRef.current = { active: false, code: null, moved: false, startY: 0 }
    setDragCode(null)
  }, [onDocMouseMove])

  const onCardMouseDown = (e, code) => {
    if (e.button !== 0) return                  // 仅左键
    if (e.target.closest('.book-actions')) return  // 点在「重命名/归档」按钮上不触发
    dragRef.current = { active: true, code, moved: false, startY: e.clientY }
    window.addEventListener('mousemove', onDocMouseMove)
    window.addEventListener('mouseup', onDocMouseUp)
  }
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
    <div className="admin-wrap connected">
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

          <div className="book-cards">
          {books == null
            ? <div className="admin-empty sm">加载中…</div>
            : books.length === 0
              ? <div className="admin-empty sm">还没有书籍，点「＋ 新建」开始</div>
              : books.map(b => (
                <div
                  key={b.code}
                  data-code={b.code}
                  className={`book-card${b.code === selected ? ' active' : ''}${b.status === 'archived' ? ' archived' : ''}${dragCode === b.code ? ' dragging' : ''}`}
                  onMouseDown={e => onCardMouseDown(e, b.code)}
                  onClick={() => {
                    if (suppressClickRef.current) { suppressClickRef.current = false; return }
                    setSelected(b.code)
                  }}
                  title="拖动可调整顺序"
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
          </div>
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

              <IntakeAddress book={current.code} base={serverBase} ossMode={ossMode} notify={notify} />

              <div className="seg seg-detail">
                <button className={view === 'manage' ? 'active' : ''} onClick={() => setView('manage')}>照片管理</button>
                <button className={view === 'board' ? 'active' : ''} onClick={() => setView('board')}>征稿看板</button>
                <button className={view === 'codes' ? 'active' : ''} onClick={() => setView('codes')}>投稿码管理</button>
              </div>

              {view === 'manage'
                ? <PhotoManage book={current.code} fail={fail} notify={notify} />
                : view === 'board'
                  ? <Board book={current.code} base={serverBase} fail={fail} notify={notify} />
                  : <Codes book={current.code} base={serverBase} fail={fail} notify={notify}
                      bookOpen={current.intake_open !== false} prefix={current.code_prefix || ''}
                      onChanged={() => loadBooks(current.code)} />}
            </>
          )}
        </section>
      </div>

      <footer className="admin-footer">
        <a
          className="footer-logo-link"
          href="https://www.sdexp.org/"
          target="_blank"
          rel="noreferrer"
          title="星尘远征队 · https://www.sdexp.org/"
        >
          <img className="footer-logo" src="/logo.png" alt="星尘远征队" />
        </a>
        <div className="footer-text">
          <a
            href="https://creativecommons.org/licenses/by-nc-sa/4.0/deed.zh"
            target="_blank"
            rel="noreferrer"
          >
            CC BY-NC-SA 4.0
          </a>
          <a
            className="footer-credit"
            href="https://www.sdexp.org/"
            target="_blank"
            rel="noreferrer"
            title="星尘远征队 · https://www.sdexp.org/"
          >
            星尘远征队 出品
          </a>
        </div>
      </footer>

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
function IntakeAddress({ book, base, ossMode, notify }) {
  const webEntry = intakeUrl(base)
  const [arch, setArch] = useState(null)   // 备份状态，主要看 rclone 是否就绪

  const loadStatus = useCallback(async () => {
    try { setArch(await api.intakeArchiveStatus(book)) } catch { /* 忽略 */ }
  }, [book])

  // 切换书籍时拉一次状态（取 rclone 就绪标志）
  useEffect(() => { loadStatus() }, [loadStatus])

  // R2 = 服务器每 15min 自动增量备份（systemd timer）。徽章反映**上一轮真实结果**：
  // 成功→绿「持续备份中·最近hh:mm」；失败→黄「备份异常」(hover 看原因)；未装 rclone→黄；
  // 就绪但还没跑过→灰「待运行」；状态未拉到→灰「检测中」。
  const mirror = arch?.mirror
  const hhmm = mirror?.at ? mirror.at.slice(11, 16) : ''
  let r2Cls = '', r2Dot = 'muted', r2Text = 'R2 备份 · 检测中…', r2Title = ''
  if (arch) {
    if (arch.rclone === false) {
      r2Cls = 'warn'; r2Dot = 'warn'; r2Text = 'R2 备份未启用（服务器未装 rclone）'
    } else if (mirror && mirror.ok === false) {
      r2Cls = 'warn'; r2Dot = 'warn'
      r2Text = `R2 备份异常${hhmm ? ' · ' + hhmm : ''}`; r2Title = mirror.msg || ''
    } else if (mirror && mirror.ok === true) {
      r2Cls = 'ok'; r2Dot = 'ok'; r2Text = `R2 持续备份中${hhmm ? ' · 最近 ' + hhmm : ''}`
    } else {
      r2Text = 'R2 持续备份 · 待运行'
    }
  }

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
          OSS {ossMode === 'oss' ? '已联动直传' : ossMode === 'local' ? '本地直存' : '检测中…'}
        </span>
        <span className={`pl-badge ${r2Cls}`} title={r2Title}>
          <i className={`dot ${r2Dot}`} />{r2Text}
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
  const [collections, setCollections] = useState([])   // 本书的相册（存片目标）
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

  const loadCollections = useCallback(async () => {
    try { setCollections((await api.intakeCollections(book)).collections || []) }
    catch { /* 相册加载失败不阻塞看板 */ }
  }, [book])

  // 切换书籍：重载并收起下钻
  useEffect(() => { setOpen(null); load(); loadCollections() }, [load, loadCollections])

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
                      <FileGrid
                        code={r.code} name={r.name} book={book} fail={fail} notify={notify}
                        collections={collections} onCollectionsChanged={loadCollections}
                      />
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

/* ── 缩略图：OSS 现出的小图偶发处理失败/限流（HEIC 等源格式更会直接报错）。
   失败时先回退原图，原图再失败才显示占位，避免黑块「刷不出来」。点占位可重试。 */
function ThumbImg({ thumb, full, alt }) {
  const thumbSrc = api.intakeImageSrc(thumb || full)
  const fullSrc = api.intakeImageSrc(full || thumb)
  // stage: 'thumb' → 加载小图；'full' → 已回退原图；'error' → 都失败
  const [stage, setStage] = useState('thumb')
  const [nonce, setNonce] = useState(0)   // 重试时强制刷新 src

  useEffect(() => { setStage('thumb'); setNonce(0) }, [thumbSrc, fullSrc])

  if (stage === 'error') {
    return (
      <span
        className="thumb-broken"
        role="button"
        title="加载失败，点击重试"
        onClick={(e) => { e.stopPropagation(); setStage('thumb'); setNonce(n => n + 1) }}
      >加载失败<br />点重试</span>
    )
  }

  const src = stage === 'thumb' ? thumbSrc : fullSrc
  const bust = nonce ? (src.includes('?') ? `&_r=${nonce}` : `?_r=${nonce}`) : ''
  return (
    <img
      src={src + bust}
      alt={alt}
      loading="lazy"
      onError={() => {
        // 小图失败且原图地址不同 → 回退原图；否则标记彻底失败
        if (stage === 'thumb' && fullSrc && fullSrc !== thumbSrc) setStage('full')
        else setStage('error')
      }}
    />
  )
}

/* ── 下钻：某摄影师的照片缩略图墙（懒加载 + 点击放大 + 多选存入文件夹）── */
function FileGrid({ code, name, book, fail, notify, collections = [], onCollectionsChanged }) {
  const [state, setState] = useState({ loading: true, files: null })
  const [lightbox, setLightbox] = useState(null)   // 当前放大的 index
  const [selecting, setSelecting] = useState(false)
  const [selected, setSelected] = useState(() => new Set())

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

  function toggle(id) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }
  function exitSelect() { setSelecting(false); setSelected(new Set()) }
  function selectAll() { setSelected(new Set(files.map(f => f.id))) }

  async function storeInto(cid, cname) {
    try {
      const r = await api.intakeCollectionAdd(cid, [...selected])
      notify?.(`已存入「${cname}」${r.added} 张`)
      onCollectionsChanged?.()
      exitSelect()
    } catch (e) { fail(e.message) }
  }

  return (
    <>
      <div className="grid-toolbar">
        {!selecting ? (
          <button className="abtn ghost sm" onClick={() => setSelecting(true)}>选择照片</button>
        ) : (
          <>
            <span className="grid-sel-count">已选 {selected.size} / {files.length}</span>
            <button className="abtn ghost sm" onClick={selectAll}>全选</button>
            <StoreMenu
              disabled={selected.size === 0}
              collections={collections}
              book={book}
              fail={fail}
              onStore={storeInto}
              onCreated={onCollectionsChanged}
            />
            <button className="abtn ghost sm" onClick={exitSelect}>退出选择</button>
          </>
        )}
      </div>
      <div className={`file-grid${selecting ? ' selecting' : ''}`}>
        {files.map((f, i) => {
          const isSel = selected.has(f.id)
          return (
            <button
              key={f.id}
              className={`thumb${isSel ? ' selected' : ''}`}
              onClick={() => selecting ? toggle(f.id) : setLightbox(i)}
              title={`${f.file_name}${f.label ? ' · ' + f.label : ''}`}
            >
              <ThumbImg thumb={f.thumb} full={f.url} alt={f.file_name} />
              {f.label && f.label !== '未命名' && <span className="thumb-label">{f.label}</span>}
              {selecting && <span className="thumb-check">{isSel ? '✓' : ''}</span>}
            </button>
          )
        })}
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

/* ── 「存入文件夹」下拉：选现有相册或新建 ── */
function StoreMenu({ disabled, collections = [], book, fail, onStore, onCreated }) {
  const dialog = useDialog()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  async function newFolder() {
    setOpen(false)
    const nm = await dialog.prompt({ title: '新建文件夹', message: '给这个相册起个名字', confirmText: '创建并存入' })
    if (!nm) return
    try {
      const c = await api.intakeCreateCollection(book, nm)
      onCreated?.()
      onStore(c.id, c.name)
    } catch (e) { fail(e.message) }
  }

  return (
    <span className="store-menu" ref={ref}>
      <button className="abtn primary sm" disabled={disabled} onClick={() => setOpen(o => !o)}>
        存入文件夹 ▾
      </button>
      {open && !disabled && (
        <div className="store-dropdown">
          {collections.length === 0 && <div className="store-empty">还没有文件夹</div>}
          {collections.map(c => (
            <button key={c.id} className="store-item" onClick={() => { setOpen(false); onStore(c.id, c.name) }}>
              <span className="store-item-name">{c.name}</span>
              <span className="store-item-count">{c.count}</span>
            </button>
          ))}
          <button className="store-item store-new" onClick={newFolder}>＋ 新建文件夹</button>
        </div>
      )}
    </span>
  )
}

/* ── 照片管理：相册（文件夹）—— 左列文件夹、右侧照片墙 + 整包下载 ── */
function PhotoManage({ book, fail, notify }) {
  const dialog = useDialog()
  const [cols, setCols] = useState(null)     // null=加载中
  const [active, setActive] = useState(null) // 当前打开的相册 id

  const load = useCallback(async () => {
    try { setCols((await api.intakeCollections(book)).collections || []) }
    catch (e) { setCols([]); fail(e.message) }
  }, [book, fail])

  useEffect(() => { setActive(null); load() }, [load])

  async function newFolder() {
    const nm = await dialog.prompt({ title: '新建文件夹', message: '给这个相册起个名字', confirmText: '创建' })
    if (!nm) return
    try {
      const c = await api.intakeCreateCollection(book, nm)
      await load()
      setActive(c.id)
      notify?.(`已新建「${c.name}」`)
    } catch (e) { fail(e.message) }
  }
  async function rename(c) {
    const nm = await dialog.prompt({ title: '重命名文件夹', defaultValue: c.name, confirmText: '保存' })
    if (!nm || nm === c.name) return
    try { await api.intakeRenameCollection(c.id, nm); await load() }
    catch (e) { fail(e.message) }
  }
  async function remove(c) {
    const ok = await dialog.confirm({
      title: '删除文件夹', danger: true, confirmText: '删除',
      message: `确定删除「${c.name}」？只移除这个相册，原投稿照片不受影响。`,
    })
    if (!ok) return
    try {
      await api.intakeDeleteCollection(c.id)
      if (active === c.id) setActive(null)
      await load()
    } catch (e) { fail(e.message) }
  }

  if (cols === null) return <div className="admin-empty">加载中…</div>
  const activeCol = cols.find(c => c.id === active)

  return (
    <div className="admin-body manage-body">
      <div className="manage-split">
        <aside className="folder-list">
          <div className="folder-head">
            <span>文件夹</span>
            <button className="abtn primary sm" onClick={newFolder}>＋ 新建</button>
          </div>
          {cols.length === 0 && <div className="grid-empty">还没有文件夹。新建后，去「征稿看板」勾选照片存进来。</div>}
          {cols.map(c => (
            <div
              key={c.id}
              className={`folder-card${c.id === active ? ' active' : ''}`}
              onClick={() => setActive(c.id)}
            >
              <div className="folder-card-main">
                <span className="folder-name">{c.name}</span>
                <span className="folder-meta">{c.count} 张 · {c.date}</span>
              </div>
              <div className="folder-actions" onClick={e => e.stopPropagation()}>
                <button className="btn-link" onClick={() => rename(c)}>重命名</button>
                <button className="btn-link del" onClick={() => remove(c)}>删除</button>
              </div>
            </div>
          ))}
        </aside>

        <section className="folder-detail">
          {!activeCol
            ? <div className="admin-empty">{cols.length ? '从左侧选择一个文件夹' : '先新建一个文件夹'}</div>
            : <FolderView
                key={activeCol.id}
                cid={activeCol.id}
                name={activeCol.name}
                fail={fail}
                notify={notify}
                onChanged={load}
              />}
        </section>
      </div>
    </div>
  )
}

/* ── 相册内照片墙：移出 / 整包下载 / 放大 ── */
function FolderView({ cid, name, fail, notify, onChanged }) {
  const [state, setState] = useState({ loading: true, files: null })
  const [selected, setSelected] = useState(() => new Set())
  const [lightbox, setLightbox] = useState(null)
  const [downloading, setDownloading] = useState(false)

  const load = useCallback(async () => {
    setState({ loading: true, files: null })
    try {
      const d = await api.intakeCollectionFiles(cid)
      setState({ loading: false, files: d.files })
    } catch (e) { setState({ loading: false, files: [] }); fail(e.message) }
  }, [cid, fail])

  useEffect(() => { setSelected(new Set()); load() }, [load])

  function toggle(id) {
    setSelected(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  }

  async function removeSelected() {
    try {
      await api.intakeCollectionRemove(cid, [...selected])
      notify?.(`已移出 ${selected.size} 张`)
      setSelected(new Set())
      await load(); onChanged?.()
    } catch (e) { fail(e.message) }
  }

  async function download() {
    setDownloading(true)
    try {
      await api.intakeDownloadCollection(cid, name)
      notify?.('已开始下载 ZIP')
    } catch (e) { fail(e.message) } finally { setDownloading(false) }
  }

  if (state.loading) return <div className="grid-empty">载入照片…</div>
  const files = state.files || []

  return (
    <>
      <div className="grid-toolbar">
        <b className="folder-title">{name}</b>
        <span className="muted">{files.length} 张</span>
        <span className="form-spacer" />
        {selected.size > 0 && (
          <button className="abtn ghost sm" onClick={removeSelected}>移出所选 {selected.size}</button>
        )}
        <button className="abtn primary sm" onClick={download} disabled={downloading || files.length === 0}>
          {downloading ? '打包中…' : '下载文件夹 (ZIP)'}
        </button>
      </div>
      {files.length === 0
        ? <div className="grid-empty">这个文件夹还没有照片。去「征稿看板」勾选照片存进来。</div>
        : (
          <div className="file-grid selecting">
            {files.map((f, i) => {
              const isSel = selected.has(f.id)
              return (
                <button
                  key={f.id}
                  className={`thumb${isSel ? ' selected' : ''}`}
                  onClick={() => toggle(f.id)}
                  onDoubleClick={() => setLightbox(i)}
                  title={`${f.file_name}　（单击选择 · 双击放大）`}
                >
                  <ThumbImg thumb={f.thumb} full={f.url} alt={f.file_name} />
                  {f.label && f.label !== '未命名' && <span className="thumb-label">{f.label}</span>}
                  <span className="thumb-check">{isSel ? '✓' : ''}</span>
                </button>
              )
            })}
          </div>
        )}
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
function Codes({ book, base, fail, notify, bookOpen = true, prefix = '', onChanged }) {
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

  async function toggleIntake() {
    const stopping = bookOpen
    if (stopping && !(await dialog.confirm({
      title: '停止本书征稿',
      message: '停止后，摄影师将无法再用投稿码上传照片（已收到的照片不受影响）。可随时恢复。',
      confirmText: '停止征稿', danger: true,
    }))) return
    try {
      await api.intakeSetBookIntake(book, !bookOpen)
      notify?.(stopping ? '已停止本书征稿' : '已恢复本书征稿')
      onChanged?.()
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
      <div className={`intake-status-bar${bookOpen ? '' : ' closed'}`}>
        <span className="intake-state">
          <span className={`dot ${bookOpen ? 'ok' : 'muted'}`} />
          {bookOpen ? '征稿进行中' : '已停止征稿'}
        </span>
        {prefix && <span className="intake-prefix">投稿码前缀 <b className="mono">{prefix}</b>（自动生成 {prefix}01、{prefix}02…）</span>}
        <span className="form-spacer" />
        <button
          className={`abtn sm ${bookOpen ? 'ghost' : 'primary'}`}
          onClick={toggleIntake}
        >{bookOpen ? '停止征稿' : '恢复征稿'}</button>
      </div>

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
