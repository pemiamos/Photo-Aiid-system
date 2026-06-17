import { useCallback, useEffect, useMemo, useState } from 'react'
import { usePhotoStore, usePhotoDispatch, Actions } from '../stores/photoStore'
import { PhotoCard } from './Gallery'
import * as api from '../services/api'
import './IndexTable.css'

const PAGE = 60
const RECENT_KEY = 'index_recent_searches'
function loadRecent() {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY)) || [] } catch { return [] }
}
function pushRecent(q) {
  const list = [q, ...loadRecent().filter(x => x !== q)].slice(0, 12)
  try { localStorage.setItem(RECENT_KEY, JSON.stringify(list)) } catch { /* 忽略 */ }
  return list
}

export default function IndexTable() {
  const { photos, settings, activeTag, searchQuery } = usePhotoStore()
  const dispatch = usePhotoDispatch()

  // ── 历史索引模式（跨全库搜索历史记录，结果瀑布展示）──
  const [globalMode, setGlobalMode] = useState(false)
  const [gq, setGq] = useState('')
  const [results, setResults] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)
  const [topTags, setTopTags] = useState([])
  const [recent, setRecent] = useState(loadRecent)

  // 进入全局模式时拉「高频关键词」（全库标签词频 TopN）
  useEffect(() => {
    if (!globalMode) return
    api.getTags()
      .then(d => setTopTags((d?.tags || []).slice(0, 20)))
      .catch(() => {})
    setRecent(loadRecent())
  }, [globalMode])

  // 全局搜索：不带 folder_path → 跨全库；分页 + 缩略图懒加载，扛上万张
  const search = useCallback(async (keyword, more = false) => {
    const q = (keyword ?? gq).trim()
    const offset = more ? results.length : 0
    setLoading(true)
    setSearched(true)
    try {
      const data = await api.getPhotos({ q: q || undefined, limit: PAGE, offset })
      const ps = data.photos || []
      setResults(more ? [...results, ...ps] : ps)
      setTotal(data.total || 0)
      if (keyword != null) setGq(q)
      if (q && !more) setRecent(pushRecent(q))
    } catch (e) {
      dispatch({ type: Actions.SET_ERROR, payload: e.message })
    } finally {
      setLoading(false)
    }
  }, [gq, results, dispatch])

  // ── 表格模式（当前文件夹）──
  const filteredPhotos = useMemo(() => {
    const normalizePath = (p) => p ? p.normalize('NFC').replace(/\\/g, '/').replace(/\/$/, '') : ''
    const currentFolder = normalizePath(settings?.folderPath)
    let list = currentFolder
      ? photos.filter(p => p.file_path && normalizePath(p.file_path).startsWith(currentFolder))
      : [...photos]

    if (searchQuery) {
      const q = searchQuery.toLowerCase()
      list = list.filter(p => {
        const hay = [p.file_name, p.ai?.category, p.ai?.description,
          ...(p.ai?.tags || [])].join(' ').toLowerCase()
        return hay.includes(q)
      })
    }
    if (activeTag) {
      list = list.filter(p => p.ai &&
        (p.ai.category === activeTag || (p.ai.tags || []).includes(activeTag)))
    }
    return list
  }, [photos, settings?.folderPath, activeTag, searchQuery])

  const fmtDate = (d) => {
    if (!d) return '—'
    const s = String(d).replace(/-/g, ':').split(' ')[0].split(':')
    return s.length >= 3 ? `${s[0]}-${s[1]}-${s[2]}` : '—'
  }

  // Combined shooting parameters (excluding GPS): focal · aperture · shutter · ISO
  const fmtShot = (exif) => {
    if (!exif) return '—'
    const parts = [
      exif.focal_length && `${Math.round(exif.focal_length)}mm`,
      exif.f_number && `f/${(+exif.f_number).toFixed(1)}`,
      exif.exposure_time && `${exif.exposure_time}s`,
      exif.iso && `ISO${exif.iso}`,
    ].filter(Boolean)
    return parts.length ? parts.join(' · ') : '—'
  }

  const handleRename = async () => {
    const analyzablePhotos = filteredPhotos.filter(p => p.ai)
    const count = analyzablePhotos.length
    if (count === 0) return
    if (!confirm(`将物理重命名磁盘上的 ${count} 个文件（不可自动恢复，但会下载日志）。\n\n确定执行？`)) return
    try {
      const ids = analyzablePhotos.map(p => p.id)
      const data = await api.renamePhotos({ photo_ids: ids })
      alert(`重命名完成：成功 ${data.success}，失败 ${data.failed}`)
      const res = await api.getAllPhotos({ folder_path: settings?.folderPath || '' })
      if (res?.photos) dispatch({ type: Actions.SET_PHOTOS, payload: res.photos })
    } catch (err) {
      dispatch({ type: Actions.SET_ERROR, payload: err.message })
    }
  }

  const handleExportCSV = async () => {
    try {
      await api.exportCSV()
    } catch (err) {
      dispatch({ type: Actions.SET_ERROR, payload: err.message })
    }
  }

  return (
    <section className="index-section">
      <div className="table-actions">
        <div className="table-actions-left">
          <button className="btn danger" onClick={handleRename}
            disabled={!photos.some(p => p.ai)}>
            ⚡ 执行物理重命名
          </button>
          <button className="btn primary" onClick={handleExportCSV}>
            导出索引 CSV
          </button>
        </div>
        <div className="table-actions-right">
          <button
            className={`btn ${globalMode ? 'primary' : 'ghost'}`}
            onClick={() => setGlobalMode(v => !v)}
            title="跨所有已索引文件夹按关键词检索历史记录"
          >
            {globalMode ? '← 返回表格' : '🕘 历史索引'}
          </button>
        </div>
      </div>

      {globalMode ? (
        <div className="gindex">
          <div className="gindex-search">
            <input
              type="text"
              value={gq}
              onChange={e => setGq(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && search()}
              placeholder="跨全库搜索：摄影师 / 地点 / 标签 / 类别 / 文件名…"
              autoFocus
            />
            <button className="btn primary" onClick={() => search()}>搜索</button>
          </div>

          {recent.length > 0 && (
            <div className="gindex-tagrow">
              <span className="gindex-label">最近</span>
              {recent.map(t => (
                <button key={t} className="token-chip" onClick={() => search(t)}>{t}</button>
              ))}
            </div>
          )}
          {topTags.length > 0 && (
            <div className="gindex-tagrow">
              <span className="gindex-label">高频</span>
              {topTags.map(t => (
                <button key={t.name} className="token-chip" onClick={() => search(t.name)}>
                  {t.name}<i className="tc-count">{t.count}</i>
                </button>
              ))}
            </div>
          )}

          <div className="gindex-meta">
            {loading && results.length === 0
              ? '搜索中…'
              : searched
                ? (total > 0 ? `共 ${total} 张${gq ? `，关键词「${gq}」` : ''}` : '没有匹配的照片')
                : '输入关键词或点上方标签开始搜索'}
          </div>

          {results.length > 0 && (
            <div className="gallery-grid">
              {results.map((p, i) => (
                <PhotoCard
                  key={p.id}
                  photo={p}
                  index={i}
                  selected={false}
                  onToggle={() => {}}
                  suggestedName={p.suggested_name}
                />
              ))}
            </div>
          )}

          {results.length < total && (
            <div className="gindex-more">
              <button className="btn ghost" disabled={loading} onClick={() => search(null, true)}>
                {loading ? '加载中…' : `加载更多（${results.length}/${total}）`}
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th style={{ width: 46 }}>帧号</th>
                <th>原文件名</th>
                <th>摄影师</th>
                <th>AI 标签</th>
                <th>地点</th>
                <th>拍摄日期</th>
                <th>相机</th>
                <th>镜头</th>
                <th>拍摄参数</th>
                <th>建议新名</th>
              </tr>
            </thead>
            <tbody>
              {filteredPhotos.map(p => (
                <tr key={p.id}>
                  <td className="mono">{String(p.id).padStart(3, '0')}</td>
                  <td className="mono">{p.file_name}</td>
                  <td>{p.ai?.photographer || <span className="faint">—</span>}</td>
                  <td>{p.ai
                    ? [p.ai.category, ...(p.ai.tags || [])].join('、')
                    : <span className="faint">—</span>}
                  </td>
                  <td>{p.ai?.location || <span className="faint">—</span>}</td>
                  <td className="mono">{fmtDate(p.exif?.date_time_original)}</td>
                  <td className="mono">{p.exif?.camera_model || '—'}</td>
                  <td className="mono">{p.exif?.lens_model || '—'}</td>
                  <td className="mono">{fmtShot(p.exif)}</td>
                  <td>{p.ai
                    ? <span className="new-name">{p.suggested_name || p.ai.category}</span>
                    : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
