import { useMemo } from 'react'
import { usePhotoStore, usePhotoDispatch, Actions } from '../stores/photoStore'
import * as api from '../services/api'
import './IndexTable.css'

export default function IndexTable() {
  const { photos, activeTag, searchQuery } = usePhotoStore()
  const dispatch = usePhotoDispatch()

  const filteredPhotos = useMemo(() => {
    let list = [...photos]
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
  }, [photos, activeTag, searchQuery])

  const fmtDate = (d) => {
    if (!d) return '—'
    const s = String(d).replace(/-/g, ':').split(' ')[0].split(':')
    return s.length >= 3 ? `${s[0]}-${s[1]}-${s[2]}` : '—'
  }

  const handleRename = async () => {
    const count = photos.filter(p => p.ai).length
    if (!confirm(`将物理重命名磁盘上的 ${count} 个文件（不可自动恢复，但会下载日志）。\n\n确定执行？`)) return
    try {
      const data = await api.renamePhotos({})
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
              <th>AI 标签</th>
              <th>拍摄日期</th>
              <th>器材</th>
              <th>建议新名</th>
            </tr>
          </thead>
          <tbody>
            {filteredPhotos.map(p => (
              <tr key={p.id}>
                <td className="mono">{String(p.id).padStart(3, '0')}</td>
                <td className="mono">{p.file_name}</td>
                <td>{p.ai
                  ? [p.ai.category, ...(p.ai.tags || [])].join('、')
                  : <span className="faint">—</span>}
                </td>
                <td className="mono">{fmtDate(p.exif?.date_time_original)}</td>
                <td className="mono">{p.exif?.camera_model || '—'}</td>
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
