/* ============================================================
   Photo-Aiid-system · API Client
   All backend communication goes through here.
   ============================================================ */

const BASE = '/api'

/* ── helpers ── */
async function request(path, options = {}) {
  const url = `${BASE}${path}`
  const config = {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  }

  try {
    const res = await fetch(url, config)
    if (!res.ok) {
      const body = await res.text()
      let msg
      try {
        const json = JSON.parse(body)
        msg = json.detail || json.message || json.error || body
      } catch {
        msg = body
      }
      throw new Error(`HTTP ${res.status}: ${msg}`)
    }
    // Some endpoints return empty 204
    if (res.status === 204) return null
    const ct = res.headers.get('content-type') || ''
    if (ct.includes('application/json')) return res.json()
    return res.text()
  } catch (err) {
    if (err.name === 'TypeError' && err.message.includes('fetch')) {
      throw new Error('无法连接后端服务，请确认 http://localhost:8000 已启动')
    }
    throw err
  }
}

/* ── Folder / Scan ── */
export async function scanFolder(folderPath) {
  return request('/scan', {
    method: 'POST',
    body: JSON.stringify({ folder_path: folderPath }),
  })
}

export async function selectFolder() {
  return request('/select-folder', {
    method: 'POST',
  })
}

export async function getScanProgress() {
  return request('/scan/progress')
}

/* ── Photos ── */
export async function getPhotos(params = {}) {
  const qs = new URLSearchParams()
  if (params.tag) qs.set('tag', params.tag)
  if (params.q) qs.set('q', params.q)
  if (params.status) qs.set('status', params.status)
  if (params.folder_path) qs.set('folder_path', params.folder_path)
  const query = qs.toString()
  return request(`/photos${query ? '?' + query : ''}`)
}

export async function getPhotoById(id) {
  return request(`/photos/${id}`)
}

/* ── Analysis ── */
export async function analyzePhotos(options = {}) {
  return request('/analyze', {
    method: 'POST',
    body: JSON.stringify(options),
  })
}

export async function getAnalysisProgress() {
  return request('/analyze/progress')
}

export async function analyzeOne(photoId) {
  return request(`/analyze/${photoId}`, { method: 'POST' })
}

/* ── Rename ── */
export async function renamePhotos(options = {}) {
  return request('/rename', {
    method: 'POST',
    body: JSON.stringify(options),
  })
}

/* ── Search ── */
export async function searchPhotos(query) {
  return request('/search', {
    method: 'POST',
    body: JSON.stringify({ query }),
  })
}

export async function semanticSearch(query) {
  return request('/search/semantic', {
    method: 'POST',
    body: JSON.stringify({ query }),
  })
}

/* ── Tags ── */
export async function getTags() {
  return request('/tags')
}

/* ── Settings ── */
export async function getSettings() {
  return request('/settings')
}

export async function updateSettings(settings) {
  return request('/settings', {
    method: 'PUT',
    body: JSON.stringify(settings),
  })
}

/* ── Export ── */
export async function exportCSV() {
  const url = `${BASE}/export/csv`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`导出失败: HTTP ${res.status}`)
  const blob = await res.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `photo-index-${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 5000)
}

export async function downloadZip() {
  const url = `${BASE}/export/zip`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`下载失败: HTTP ${res.status}`)
  const blob = await res.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `renamed-photos-${new Date().toISOString().slice(0, 10)}.zip`
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 5000)
}

/* ── Health ── */
export async function healthCheck() {
  return request('/health')
}
