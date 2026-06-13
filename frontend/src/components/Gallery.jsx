import { useState, useMemo } from 'react'
import { usePhotoStore, usePhotoDispatch, Actions } from '../stores/photoStore'
import * as api from '../services/api'
import './Gallery.css'

function PhotoCard({ photo, index }) {
  const frame = `SDX-${String(photo.id).padStart(3, '0')}A`
  const ai = photo.ai || {}
  const exif = photo.exif || {}
  const exifLine = [exif.camera_model, exif.focal_length && `${Math.round(exif.focal_length)}mm`,
    exif.f_number && `f/${exif.f_number}`, exif.iso && `ISO${exif.iso}`].filter(Boolean).join(' · ')

  const fmtDate = (d) => {
    if (!d) return '—'
    const s = String(d).replace(/-/g, ':').split(' ')[0].split(':')
    return s.length >= 3 ? `${s[0]}${s[1]}${s[2]}` : '—'
  }

  const statusLabel = { queued: '待分析', analyzing: '识别中…', error: '失败', done: '' }
  const statusClass = photo.scan_status || 'queued'

  return (
    <div className="photo-card">
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
        {statusClass !== 'done' && (
          <span className={`card-status ${statusClass}`}>
            {statusLabel[statusClass] || ''}
          </span>
        )}
      </div>
      <div className="card-meta">
        <div className="card-fname">{photo.file_name}</div>
        {ai.category && (
          <>
            <div className="card-newname">→ {photo.suggested_name || ai.category}</div>
            <div className="card-desc">{ai.description || ''}</div>
            <div className="card-tags">
              {[ai.category, ...(ai.tags || [])].map((t, i) => (
                <span key={i} className="card-tag">{t}</span>
              ))}
            </div>
          </>
        )}
        {exifLine && <div className="card-exif">{exifLine}</div>}
      </div>
    </div>
  )
}

export default function Gallery() {
  const { photos, settings, activeTag, searchQuery, analysisProgress, engineStatus } = usePhotoStore()
  const dispatch = usePhotoDispatch()
  const [localQuery, setLocalQuery] = useState('')

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

      {showProgress && (
        <div className="progress-bar-wrap">
          <div className="progress-text">
            AI 分析中 {analysisProgress.current}/{analysisProgress.total}
          </div>
          <div className="progress-track">
            <div
              className="progress-fill"
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
            <PhotoCard key={photo.id} photo={photo} index={i} />
          ))}
        </div>
      )}
    </section>
  )
}
