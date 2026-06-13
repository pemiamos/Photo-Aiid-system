import { useState, useMemo } from 'react'
import { usePhotoStore, usePhotoDispatch, Actions } from '../stores/photoStore'
import * as api from '../services/api'
import './Gallery.css'

function PhotoCard({ photo, index, selected, onToggle }) {
  const dispatch = usePhotoDispatch()
  const ai = photo.ai || {}
  const [editing, setEditing] = useState(false)
  const [loc, setLoc] = useState(ai.location || '')
  const [tagStr, setTagStr] = useState((ai.tags || []).join(', '))
  const [saving, setSaving] = useState(false)

  const startEdit = (e) => {
    e.stopPropagation()
    setLoc(ai.location || '')
    setTagStr((ai.tags || []).join(', '))
    setEditing(true)
  }

  const saveEdit = async (e) => {
    e.stopPropagation()
    setSaving(true)
    try {
      const tags = tagStr.split(/[,，]/).map(t => t.trim()).filter(Boolean)
      const updated = await api.editPhotoAI(photo.id, { tags, location: loc.trim() })
      if (updated) dispatch({ type: Actions.UPDATE_PHOTO, payload: updated })
      setEditing(false)
    } catch (err) {
      dispatch({ type: Actions.SET_ERROR, payload: err.message })
    } finally {
      setSaving(false)
    }
  }

  const frame = `SDX-${String(photo.id).padStart(3, '0')}A`
  const exif = photo.exif || {}
  // Full EXIF (excluding GPS) shown under the thumbnail.
  const exifGear = [exif.camera_model, exif.lens_model].filter(Boolean).join(' · ')
  const exifShot = [
    exif.focal_length && `${Math.round(exif.focal_length)}mm`,
    exif.f_number && `f/${(+exif.f_number).toFixed(1)}`,
    exif.exposure_time && `${exif.exposure_time}s`,
    exif.iso && `ISO${exif.iso}`,
  ].filter(Boolean).join(' · ')

  const fmtDate = (d) => {
    if (!d) return '—'
    const s = String(d).replace(/-/g, ':').split(' ')[0].split(':')
    return s.length >= 3 ? `${s[0]}${s[1]}${s[2]}` : '—'
  }

  const statusLabel = { queued: '待分析', analyzing: '识别中…', error: '失败', done: '' }
  const statusClass = photo.scan_status || 'queued'

  return (
    <div
      className={`photo-card${selected ? ' selected' : ''}${editing ? ' editing' : ''}`}
      onClick={() => { if (!editing) onToggle(photo.id) }}
      title={editing ? '' : '点击选中 / 取消，用于「自选分析」'}
    >
      <div className="card-edge">
        <span>{frame}</span>
        <span className="card-perf">▸▸▸▸▸▸▸▸</span>
        <span>{fmtDate(exif.date_time_original)}</span>
      </div>
      <div className="card-img-wrap">
        <img
          src={`/api/thumbnails/${photo.id}`}
          alt={photo.file_name}
          loading="lazy"
        />
        <span className={`card-check${selected ? ' on' : ''}`}>✓</span>
        {statusClass !== 'done' && (
          <span className={`card-status ${statusClass}`}>
            {statusLabel[statusClass] || ''}
          </span>
        )}
      </div>
      <div className="card-meta">
        <div className="card-fname">
          {photo.file_name}
          {ai.category && !editing && (
            <button className="card-edit-btn" onClick={startEdit} title="编辑描述/标签">✏️</button>
          )}
        </div>
        {ai.category && !editing && (
          <>
            <div className="card-newname">→ {photo.suggested_name || ai.category}</div>
            {ai.location && <div className="card-location">📍 {ai.location}</div>}
            <div className="card-tags">
              {[ai.category, ...(ai.tags || [])].map((t, i) => (
                <span key={i} className="card-tag">{t}</span>
              ))}
            </div>
          </>
        )}
        {editing && (
          <div className="card-editor" onClick={e => e.stopPropagation()}>
            <label>地点</label>
            <input type="text" value={loc} onChange={e => setLoc(e.target.value)} />
            <label>标签（逗号分隔）</label>
            <input type="text" value={tagStr} onChange={e => setTagStr(e.target.value)} />
            <div className="card-editor-actions">
              <button className="ed-save" onClick={saveEdit} disabled={saving}>
                {saving ? '保存中…' : '保存'}
              </button>
              <button className="ed-cancel" onClick={e => { e.stopPropagation(); setEditing(false) }}>取消</button>
            </div>
          </div>
        )}
        {(exifGear || exifShot) && (
          <div className="card-exif">
            {exifGear && <div className="exif-row">📷 {exifGear}</div>}
            {exifShot && <div className="exif-row">⚙ {exifShot}</div>}
          </div>
        )}
      </div>
    </div>
  )
}

function fmtDuration(sec) {
  if (sec == null || isNaN(sec)) return '—'
  const s = Math.max(0, Math.round(sec))
  const m = Math.floor(s / 60)
  const r = s % 60
  return m > 0 ? `${m}分${r}秒` : `${r}秒`
}

export default function Gallery() {
  const { photos, settings, activeTag, searchQuery, analysisProgress, engineStatus, selectedIds } = usePhotoStore()
  const dispatch = usePhotoDispatch()
  const [localQuery, setLocalQuery] = useState('')
  const [batchOpen, setBatchOpen] = useState(false)
  const [batchLoc, setBatchLoc] = useState('')
  const [batchAddTags, setBatchAddTags] = useState('')

  const toggleSelect = (id) => dispatch({ type: Actions.TOGGLE_SELECT, payload: id })

  const applyBatchEdit = async () => {
    const add_tags = batchAddTags.split(/[,，]/).map(t => t.trim()).filter(Boolean)
    if (!batchLoc.trim() && add_tags.length === 0) return
    try {
      await api.batchEditAI({
        photo_ids: selectedIds,
        location: batchLoc.trim() || null,
        add_tags: add_tags.length ? add_tags : null,
      })
      const data = await api.getPhotos({ folder_path: settings?.folderPath || '' })
      if (data?.photos) dispatch({ type: Actions.SET_PHOTOS, payload: data.photos })
      setBatchLoc(''); setBatchAddTags(''); setBatchOpen(false)
    } catch (err) {
      dispatch({ type: Actions.SET_ERROR, payload: err.message })
    }
  }

  const filteredPhotos = useMemo(() => {
    const normalizePath = (p) => p ? p.normalize('NFC').replace(/\\/g, '/').replace(/\/$/, '') : ''
    const currentFolder = normalizePath(settings?.folderPath)
    let list = currentFolder
      ? photos.filter(p => p.file_path && normalizePath(p.file_path).startsWith(currentFolder))
      : [...photos]

    const q = (searchQuery || localQuery).toLowerCase()
    if (q) {
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
  }, [photos, settings?.folderPath, activeTag, searchQuery, localQuery])

  const handleSearch = (e) => {
    setLocalQuery(e.target.value)
    dispatch({ type: Actions.SET_SEARCH_RESULTS, payload: null })
  }

  const handleSemantic = async () => {
    if (!localQuery.trim()) return
    try {
      const data = await api.semanticSearch(localQuery)
      if (data?.photos) {
        dispatch({ type: Actions.SET_PHOTOS, payload: data.photos })
      }
    } catch (err) {
      dispatch({ type: Actions.SET_ERROR, payload: err.message })
    }
  }

  const handleTogglePause = async () => {
    const paused = analysisProgress?.paused
    // Optimistic update; polling will reconcile within ~1s.
    dispatch({
      type: Actions.SET_ANALYSIS_PROGRESS,
      payload: { ...analysisProgress, paused: !paused },
    })
    try {
      if (paused) await api.resumeAnalysis()
      else await api.pauseAnalysis()
    } catch (err) {
      dispatch({ type: Actions.SET_ERROR, payload: err.message })
    }
  }

  const showProgress = engineStatus === 'busy' && analysisProgress

  return (
    <section className="gallery-section">
      <div className="search-row">
        <input
          type="text"
          placeholder="搜索：输入关键词即时过滤，或用自然语言描述后点「语义搜索」"
          value={localQuery}
          onChange={handleSearch}
          onKeyDown={e => e.key === 'Enter' && handleSemantic()}
        />
        <button className="search-btn" onClick={handleSemantic}>语义搜索</button>
      </div>

      {filteredPhotos.length > 0 && (
        <div className="select-row">
          <span className="select-info">
            已选 <b>{selectedIds.length}</b> / {filteredPhotos.length}
          </span>
          <button
            className="select-btn"
            onClick={() => dispatch({
              type: Actions.SET_SELECTED,
              payload: filteredPhotos.map(p => p.id),
            })}
          >
            全选本页
          </button>
          <button
            className="select-btn"
            onClick={() => dispatch({ type: Actions.CLEAR_SELECTION })}
            disabled={selectedIds.length === 0}
          >
            取消选择
          </button>
          <button
            className="select-btn"
            onClick={() => setBatchOpen(o => !o)}
            disabled={selectedIds.length === 0}
          >
            批量编辑
          </button>
        </div>
      )}

      {batchOpen && selectedIds.length > 0 && (
        <div className="batch-editor">
          <div className="batch-title">批量编辑 {selectedIds.length} 张</div>
          <input
            type="text"
            placeholder="统一设为地点（留空则不改），如 苏州-甪直"
            value={batchLoc}
            onChange={e => setBatchLoc(e.target.value)}
          />
          <input
            type="text"
            placeholder="追加标签，逗号分隔（如 精选, 已选用）"
            value={batchAddTags}
            onChange={e => setBatchAddTags(e.target.value)}
          />
          <div className="batch-actions">
            <button className="ed-save" onClick={applyBatchEdit}>应用到选中</button>
            <button className="ed-cancel" onClick={() => setBatchOpen(false)}>关闭</button>
          </div>
        </div>
      )}

      {showProgress && (
        <div className="progress-bar-wrap">
          <div className="progress-text">
            <span>
              {analysisProgress.paused ? '已暂停' : 'AI 分析中'}{' '}
              {analysisProgress.current}/{analysisProgress.total}
            </span>
            <span className="progress-time">
              已用 {fmtDuration(analysisProgress.elapsed)}
              {analysisProgress.eta != null && !analysisProgress.paused
                ? ` · 预计剩余 ${fmtDuration(analysisProgress.eta)}` : ''}
            </span>
            <button className="pause-btn" onClick={handleTogglePause}>
              {analysisProgress.paused ? '继续' : '暂停'}
            </button>
          </div>
          <div className="progress-track">
            <div
              className={`progress-fill${analysisProgress.paused ? ' paused' : ''}`}
              style={{ width: `${analysisProgress.total ? (analysisProgress.current / analysisProgress.total) * 100 : 0}%` }}
            />
          </div>
        </div>
      )}

      {filteredPhotos.length === 0 ? (
        <div className="empty-state">
          <b>暗房已就绪</b>
          <span>在左侧输入文件夹路径并扫描，AI 将自动识别内容、提取 EXIF、生成标签与建议文件名</span>
        </div>
      ) : (
        <div className="gallery-grid">
          {filteredPhotos.map((photo, i) => (
            <PhotoCard
              key={photo.id}
              photo={photo}
              index={i}
              selected={selectedIds.includes(photo.id)}
              onToggle={toggleSelect}
            />
          ))}
        </div>
      )}
    </section>
  )
}
