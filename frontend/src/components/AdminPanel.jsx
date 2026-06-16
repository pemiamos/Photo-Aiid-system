import { useEffect, useState, useCallback } from 'react'
import { usePhotoDispatch, Actions } from '../stores/photoStore'
import * as api from '../services/api'
import './AdminPanel.css'

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

  return <Console fail={fail} onDisconnect={disconnect} />
}

/* ── 已连接主控制台 ── */
function Console({ fail, onDisconnect }) {
  const [books, setBooks] = useState(null)
  const [selected, setSelected] = useState('')   // 选中书籍 code
  const [view, setView] = useState('board')       // board | codes
  const [showNew, setShowNew] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [ossMode, setOssMode] = useState('')      // oss | local

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
    if (next === 'archived' && !window.confirm(`归档书籍《${b.title}》？归档后不再征稿，但数据保留。`)) return
    try {
      await api.intakeSetBookStatus(b.code, next)
      await loadBooks()
    } catch (e) { fail(e.message) }
  }

  async function rename(b) {
    const title = window.prompt('重命名书籍', b.title)
    if (title == null || !title.trim() || title.trim() === b.title) return
    try {
      await api.intakeRenameBook(b.code, title.trim())
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

              <IntakeAddress book={current.code} base={serverBase} ossMode={ossMode} fail={fail} />

              <div className="seg seg-detail">
                <button className={view === 'board' ? 'active' : ''} onClick={() => setView('board')}>征稿看板</button>
                <button className={view === 'codes' ? 'active' : ''} onClick={() => setView('codes')}>投稿码管理</button>
              </div>

              {view === 'board'
                ? <Board book={current.code} fail={fail} />
                : <Codes book={current.code} base={serverBase} fail={fail} onChanged={() => loadBooks(current.code)} />}
            </>
          )}
        </section>
      </div>
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
function IntakeAddress({ book, base, ossMode, fail }) {
  const webEntry = intakeUrl(base)
  const archiveCmd = `bash scripts/archive-to-r2.sh ${book}`
  return (
    <div className="intake-addr">
      <div className="intake-addr-main">
        <div className="intake-addr-label">投稿地址</div>
        <code className="intake-addr-url" title={webEntry}>{webEntry}</code>
        <button className="abtn primary sm" onClick={() => copyText(webEntry, '网页投稿入口', fail)}>复制网页入口</button>
        <button className="abtn ghost sm" onClick={() => copyText(base, 'App 服务器地址', fail)}>复制 App 服务器地址</button>
      </div>
      <div className="pipeline">
        <span className="pl-badge ok"><i className="dot ok" />征稿服务器 已连接</span>
        <span className={`pl-badge ${ossMode === 'oss' ? 'ok' : 'warn'}`}>
          <i className={`dot ${ossMode === 'oss' ? 'ok' : 'warn'}`} />
          阿里云 OSS {ossMode === 'oss' ? '已联动直传' : ossMode === 'local' ? '本地直存' : '检测中…'}
        </span>
        <span className="pl-badge" title={archiveCmd}>
          <i className="dot muted" />R2 归档（手动）
          <button className="btn-link copy" onClick={() => copyText(archiveCmd, '归档命令', fail)}>复制命令</button>
        </span>
      </div>
    </div>
  )
}

/* ── 征稿看板 ── */
function Board({ book, fail }) {
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setBusy(true)
    try {
      setData(await api.intakeBoard(book))
    } catch (e) {
      fail(e.message)
    } finally {
      setBusy(false)
    }
  }, [book, fail])

  useEffect(() => { load() }, [load])

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
        <button className="abtn ghost sm refresh" onClick={load} disabled={busy}>刷新</button>
      </div>

      <table className="admin-table">
        <thead>
          <tr><th>投稿码</th><th>姓名</th><th>状态</th><th>张数</th><th>大小</th><th>标注分布</th></tr>
        </thead>
        <tbody>
          {data.rows.map(r => (
            <tr key={r.code} className={r.submitted ? '' : 'row-pending'}>
              <td className="mono">{r.code}</td>
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
          ))}
          {data.rows.length === 0 && (
            <tr><td colSpan={6} className="muted" style={{ textAlign: 'center', padding: '24px' }}>
              本书还没有投稿码，去「投稿码管理」新增
            </td></tr>
          )}
        </tbody>
      </table>
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
function Codes({ book, base, fail, onChanged }) {
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [name, setName] = useState('')
  const [contact, setContact] = useState('')
  const [code, setCode] = useState('')
  const [batch, setBatch] = useState('')
  const [showBatch, setShowBatch] = useState(false)

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
      if (res.created) fail(`已生成 ${res.created.length} 个投稿码`)
    } catch (err) { fail(err.message) }
  }

  async function remove(r) {
    if (r.files > 0) { fail('该摄影师已有投稿，不能删除'); return }
    if (!window.confirm(`删除投稿码 ${r.code}（${r.name}）？`)) return
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
        <span className="codes-count muted">共 {data?.rows?.length || 0} 个投稿码</span>
        <span className="form-spacer" />
        <button className="abtn ghost sm" onClick={exportCsv}>↓ 导出全部投稿码</button>
      </div>

      <table className="admin-table">
        <thead>
          <tr><th>投稿码</th><th>姓名</th><th>联系方式</th><th>专属投稿链接</th><th></th></tr>
        </thead>
        <tbody>
          {(data?.rows || []).map(r => (
            <tr key={r.id}>
              <td className="mono">{r.code}</td>
              <td>{r.name}</td>
              <td className="muted">{r.contact || '—'}</td>
              <td>
                <button
                  className="btn-link copy"
                  onClick={() => copyText(intakeUrl(base, r.code), `${r.name} 的投稿链接`, fail)}
                  title={intakeUrl(base, r.code)}
                >复制链接</button>
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
          {(data?.rows || []).length === 0 && (
            <tr><td colSpan={5} className="muted" style={{ textAlign: 'center', padding: '24px' }}>
              还没有投稿码，用上方表单新增
            </td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
