import { useState, useMemo, useEffect, useRef } from 'react'
import { usePhotoStore, usePhotoDispatch, Actions } from '../stores/photoStore'
import * as api from '../services/api'
import './Gallery.css'

// 把过长文件名拆成「开头 + 结尾(含扩展名)」两段，配合 CSS 做中段省略，
// 这样既看得到扩展名、也能区分同前缀的文件，而不是只留开头一截。
function splitFileName(name) {
  if (!name) return ['', '']
  const dot = name.lastIndexOf('.')
  const ext = dot > 0 ? name.slice(dot) : ''
  const stem = dot > 0 ? name.slice(0, dot) : name
  const TAIL = 5 // 结尾主名保留的字符数
  if (stem.length <= TAIL + 6) return [stem, ext]
  return [stem.slice(0, stem.length - TAIL), stem.slice(-TAIL) + ext]
}

export function PhotoCard({ photo, index, selected, onToggle, onOpen, suggestedName }) {
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

  // 原图规格：像素尺寸 + 文件大小，显示在第 3 行右侧。
  const fmtBytes = (b) => {
    if (!b) return ''
    if (b >= 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`
    if (b >= 1024) return `${Math.round(b / 1024)} KB`
    return `${b} B`
  }
  const dims = photo.width && photo.height ? `${photo.width}×${photo.height}` : ''
  const specs = [dims, fmtBytes(photo.file_size)].filter(Boolean).join(' · ')

  // 拖拽到桌面/文件夹时复制原图；已分析则用建议新名（suggestedName 含扩展名），
  // 未分析则用原文件名。依赖 Chromium 的 DownloadURL 机制。
  const MIME_BY_EXT = {
    jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png',
    gif: 'image/gif', webp: 'image/webp', tif: 'image/tiff',
    tiff: 'image/tiff', bmp: 'image/bmp', heic: 'image/heic', heif: 'image/heif',
  }
  const handleDragStart = (e) => {
    if (editing) return
    const downloadName = suggestedName || photo.file_name
    const ext = (downloadName.split('.').pop() || '').toLowerCase()
    const mime = MIME_BY_EXT[ext] || 'application/octet-stream'
    const url = api.originalUrl(photo.id)
    // DownloadURL 让浏览器把拖出的内容保存为文件（Chrome / Edge 支持）。
    e.dataTransfer.setData('DownloadURL', `${mime}:${downloadName}:${url}`)
    e.dataTransfer.setData('text/uri-list', url)
    e.dataTransfer.setData('text/plain', url)
    e.dataTransfer.effectAllowed = 'copy'
  }

  return (
    <div
      className={`photo-card${selected ? ' selected' : ''}${editing ? ' editing' : ''}`}
      draggable={!editing}
      onDragStart={handleDragStart}
    >
      <div className="card-edge">
        <span>{frame}</span>
        <span className="card-perf">▸▸▸▸▸▸▸▸</span>
        <span>{fmtDate(exif.date_time_original)}</span>
      </div>
      <div
        className="card-img-wrap"
        onClick={() => { if (!editing) onOpen() }}
        title={editing ? '' : '点击放大查看；拖到文件夹或桌面可复制原图'}
      >
        <img
          src={`/api/thumbnails/${photo.id}`}
          alt={photo.file_name}
          loading="lazy"
        />
        <span
          className={`card-check${selected ? ' on' : ''}`}
          onClick={(e) => { e.stopPropagation(); onToggle(photo.id) }}
          title="选中 / 取消（用于「自选分析」与投稿）"
        >✓</span>
        {statusClass !== 'done' && (
          <span
            className={`card-status ${statusClass}`}
            title={statusClass === 'error' ? (photo.error_message || '分析失败（原因未知）') : ''}
          >
            {statusLabel[statusClass] || ''}
          </span>
        )}
      </div>
      <div className="card-meta">
        <div className="card-fname">
          <span className="card-fname-name" title={photo.file_name}>
            {(() => {
              const [head, tail] = splitFileName(photo.file_name)
              return (<>
                <span className="fname-head">{head}</span>
                <span className="fname-tail">{tail}</span>
              </>)
            })()}
            {ai.category && !editing && (
              <button className="card-edit-btn" onClick={startEdit} title="编辑描述/标签">✏️</button>
            )}
          </span>
          {ai.category && !editing && (
            <span className="card-category">{ai.category}</span>
          )}
        </div>
        {ai.category && !editing && (
          <>
            <div className="card-newname">→ {suggestedName || '（拟重命名生成中…）'}</div>
            {(ai.location || specs) && (
              <div className="card-location">
                <span className="card-loc-text">{ai.location ? `📍 ${ai.location}` : ''}</span>
                {specs && <span className="card-specs">{specs}</span>}
              </div>
            )}
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
  const { photos, settings, activeTag, searchQuery, analysisProgress, engineStatus, selectedIds, submitMode, renamePreviewNonce } = usePhotoStore()
  const dispatch = usePhotoDispatch()
  const [localQuery, setLocalQuery] = useState('')
  const [batchOpen, setBatchOpen] = useState(false)
  const [batchLoc, setBatchLoc] = useState('')
  const [batchAddTags, setBatchAddTags] = useState('')

  const toggleSelect = (id) => dispatch({ type: Actions.TOGGLE_SELECT, payload: id })

  // 单击缩略图放大查看（与征稿看板一致）：记录在过滤集合中的下标，支持左右切换。
  const [lightboxIndex, setLightboxIndex] = useState(null)

  /* ── 拖文件夹进画廊：直接扫描并切到该文件夹展示（Tauri 桌面端可拿到真实路径）── */
  const [folderDragOver, setFolderDragOver] = useState(false)
  const onGalleryDragOver = (e) => {
    if (submitMode) return
    if (e.dataTransfer?.types?.includes('Files')) {
      e.preventDefault()
      e.dataTransfer.dropEffect = 'copy'
      setFolderDragOver(true)
    }
  }
  const onGalleryDragLeave = (e) => {
    // 只在真正离开画廊区域时收起（忽略子元素之间的冒泡）
    if (e.currentTarget.contains(e.relatedTarget)) return
    setFolderDragOver(false)
  }
  const onGalleryDrop = (e) => {
    e.preventDefault()
    setFolderDragOver(false)
    if (submitMode) return
    const file = e.dataTransfer.files?.[0]
    let path = file?.path
    if (!path) {
      // 纯浏览器拿不到绝对路径，只有 Tauri/桌面端可用
      dispatch({ type: Actions.SET_ERROR, payload: '拖拽文件夹需在桌面 App 中使用（浏览器无法获取文件夹路径），请改用侧栏「浏览」。' })
      return
    }
    // 拖的是文件则取其所在目录
    if (/\.[a-zA-Z0-9]+$/.test(path)) {
      const i = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'))
      if (i > 0) path = path.slice(0, i)
    }
    dispatch({ type: Actions.SET_SETTINGS, payload: { folderPath: path } })
    dispatch({ type: Actions.SET_SCAN_STATUS, payload: 'scanning' })
    api.scanFolder(path).catch(err => {
      dispatch({ type: Actions.SET_ERROR, payload: err.message })
      dispatch({ type: Actions.SET_SCAN_STATUS, payload: 'idle' })
    })
  }

  const applyBatchEdit = async () => {
    const add_tags = batchAddTags.split(/[,，]/).map(t => t.trim()).filter(Boolean)
    if (!batchLoc.trim() && add_tags.length === 0) return
    try {
      await api.batchEditAI({
        photo_ids: selectedIds,
        location: batchLoc.trim() || null,
        add_tags: add_tags.length ? add_tags : null,
      })
      const data = await api.getAllPhotos({ folder_path: settings?.folderPath || '' })
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

  // 拉取每张照片的「拟重命名」预览（后端按当前模板/前缀计算，含去重与地名优先逻辑）
  const [previewMap, setPreviewMap] = useState({})
  const doneIds = useMemo(
    () => filteredPhotos.filter(p => p.ai).map(p => p.id),
    [filteredPhotos]
  )
  // 注意：key 必须包含影响命名的 ai 内容（摄影师/地点/类别/标签），不能只看 id 列表。
  // 否则重新分析后照片 id 不变、ai 内容已变，预览却不会重新拉取（会停留在旧名）。
  const previewKey = useMemo(() => {
    const sig = filteredPhotos
      .filter(p => p.ai)
      .map(p => {
        const a = p.ai || {}
        const tags = Array.isArray(a.tags) ? a.tags.join('+') : ''
        return `${p.id}:${a.photographer || ''}:${a.location || ''}:${a.category || ''}:${tags}`
      })
      .join('|')
    // 末尾带上 nonce：侧栏「刷新」按钮 bump 它即可强制重算（即使其它都没变）。
    return `${sig}|${settings?.template || ''}|${settings?.prefix || ''}|${renamePreviewNonce}`
  }, [filteredPhotos, settings?.template, settings?.prefix, renamePreviewNonce])
  useEffect(() => {
    if (doneIds.length === 0) { setPreviewMap({}); return }
    let cancelled = false
    // 关键：把当前模板/前缀一并传给后端，让预览用「侧栏正在编辑的模板」即时计算，
    // 不再依赖后端数据库里上次同步的旧模板（这正是改字段后画廊不更新的根因）。
    api.renamePreview({ photo_ids: doneIds, template: settings?.template, prefix: settings?.prefix })
      .then(data => {
        if (cancelled || !data?.entries) return
        const m = {}
        for (const e of data.entries) m[e.photo_id] = e.new_name
        setPreviewMap(m)
      })
      .catch(() => {})
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewKey])

  // ── 渐进式渲染（避免一次性挂载上千张卡片导致卡顿）──
  // 数据已全部加载在 filteredPhotos 中（全选/搜索/过滤都作用于完整集合），
  // 这里只控制实际挂载到 DOM 的卡片数量：初始一批，滚动接近底部时再追加。
  const GALLERY_CHUNK = 120
  const [visibleCount, setVisibleCount] = useState(GALLERY_CHUNK)
  const sentinelRef = useRef(null)
  // 过滤结果变化时（切文件夹/搜索/标签）重置回第一批。
  useEffect(() => { setVisibleCount(GALLERY_CHUNK) }, [filteredPhotos])
  // 哨兵进入视口附近就追加一批，直到铺满当前过滤集合。
  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return
    const io = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting) {
        setVisibleCount(c => Math.min(c + GALLERY_CHUNK, filteredPhotos.length))
      }
    }, { rootMargin: '800px 0px' })
    io.observe(el)
    return () => io.disconnect()
  }, [filteredPhotos.length, visibleCount])
  const visiblePhotos = useMemo(
    () => filteredPhotos.slice(0, visibleCount),
    [filteredPhotos, visibleCount]
  )

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
    <section
      className={`gallery-section${folderDragOver ? ' folder-drag' : ''}`}
      onDragOver={onGalleryDragOver}
      onDragLeave={onGalleryDragLeave}
      onDrop={onGalleryDrop}
    >
      {folderDragOver && (
        <div className="folder-drop-overlay">
          <div className="folder-drop-card">
            <div className="fdo-icon">📂</div>
            松开即扫描并展示该文件夹
          </div>
        </div>
      )}
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
          {submitMode && (
            <button
              className="select-btn submit-confirm"
              onClick={() => dispatch({ type: Actions.SET_ACTIVE_TAB, payload: 'submit' })}
              disabled={selectedIds.length === 0}
              title="确认所选照片，进入提交页"
            >
              确认投稿 ({selectedIds.length})
            </button>
          )}
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
        <>
          <div className="gallery-grid">
            {visiblePhotos.map((photo, i) => (
              <PhotoCard
                key={photo.id}
                photo={photo}
                index={i}
                selected={selectedIds.includes(photo.id)}
                onToggle={toggleSelect}
                onOpen={() => setLightboxIndex(i)}
                suggestedName={previewMap[photo.id]}
              />
            ))}
          </div>
          {visibleCount < filteredPhotos.length && (
            <div ref={sentinelRef} className="gallery-sentinel">
              正在加载更多…（{visibleCount} / {filteredPhotos.length}）
            </div>
          )}
        </>
      )}

      {lightboxIndex != null && filteredPhotos[lightboxIndex] && (
        <GalleryLightbox
          photos={filteredPhotos}
          index={lightboxIndex}
          onClose={() => setLightboxIndex(null)}
          onNav={(d) => setLightboxIndex(i => (i + d + filteredPhotos.length) % filteredPhotos.length)}
        />
      )}
    </section>
  )
}

/* ── 放大查看（复用征稿看板的 .lightbox 样式，带左右切换 / Esc 关闭 / 元信息）── */
function GalleryLightbox({ photos, index, onClose, onNav }) {
  const p = photos[index]
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowLeft') onNav(-1)
      else if (e.key === 'ArrowRight') onNav(1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, onNav])
  if (!p) return null

  const ai = p.ai || {}
  const dims = p.width && p.height ? `${p.width}×${p.height}` : ''
  const meta = [`${index + 1}/${photos.length}`, ai.category, ai.location, dims]
    .filter(Boolean).join(' · ')

  return (
    <div className="lightbox gallery-lightbox" onClick={onClose}>
      <div className="lb-stage" onClick={e => e.stopPropagation()}>
        <button className="lb-nav prev" onClick={() => onNav(-1)} aria-label="上一张">‹</button>
        <img src={api.originalUrl(p.id)} alt={p.file_name} />
        <button className="lb-nav next" onClick={() => onNav(1)} aria-label="下一张">›</button>
        <div className="lb-info">
          <span className="lb-name">{p.file_name}</span>
          <span className="lb-meta">{meta}</span>
        </div>
        <button className="lb-close" onClick={onClose} aria-label="关闭">✕</button>
      </div>
    </div>
  )
}
