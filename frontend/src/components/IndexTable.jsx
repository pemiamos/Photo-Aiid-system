import { useMemo } from 'react'
import { usePhotoStore, usePhotoDispatch, Actions } from '../stores/photoStore'
import * as api from '../services/api'
import './IndexTable.css'

export default function IndexTable() {
  const { photos, settings, activeTag, searchQuery } = usePhotoStore()
  const dispatch = usePhotoDispatch()

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
      // Refresh photos
      const res = await api.getPhotos()
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
        <button className="btn danger" onClick={handleRename}
          disabled={!photos.some(p => p.ai)}>
          ⚡ 执行物理重命名
        </button>
        <button className="btn primary" onClick={handleExportCSV}>
          导出索引 CSV
        </button>
      </div>

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
    </section>
  )
}
