/* ============================================================
   Photo-Aiid-system · API Client
   All backend communication goes through here.
   ============================================================ */

const BASE = '/api'

/* ── helpers ── */
// FastAPI `detail` may be a string, an object, or an array of validation-error
// objects ({loc, msg, type}). Flatten any of these into readable text so the UI
// never shows "[object Object]".
function formatDetail(detail) {
  if (!detail) return ''
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map(d => {
        if (typeof d === 'string') return d
        const loc = Array.isArray(d.loc) ? d.loc.join('.') : d.loc
        return [loc, d.msg].filter(Boolean).join(': ')
      })
      .join('; ')
  }
  if (typeof detail === 'object') return detail.msg || JSON.stringify(detail)
  return String(detail)
}

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
        msg = formatDetail(json.detail) || json.message || json.error || body
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
  if (params.category) qs.set('category', params.category)
  if (params.folder_path) qs.set('folder_path', params.folder_path)
  if (params.limit != null) qs.set('limit', params.limit)
  if (params.offset != null) qs.set('offset', params.offset)
  const query = qs.toString()
  return request(`/photos${query ? '?' + query : ''}`)
}

// 加载整个画廊（不分页）。不显式传 limit 时后端默认只返回 200 张，
// 这里用一个足够大的上限把当前文件夹的全部照片一次取回。
export async function getAllPhotos(params = {}) {
  return getPhotos({ limit: 100000, ...params })
}

/* ── 已索引文件夹注册表 ── */
export async function listFolders() {
  return request('/folders')
}
export async function removeFolder(path) {
  return request('/folders/remove', { method: 'POST', body: JSON.stringify({ path }) })
}
export async function clearFolders() {
  return request('/folders/clear', { method: 'POST' })
}
export async function cleanStaleFolders() {
  return request('/folders/clean-stale', { method: 'POST' })
}

export async function getPhotoById(id) {
  return request(`/photos/${id}`)
}

// Absolute URL of a photo's full-resolution original. Used by the gallery's
// drag-to-desktop feature (the browser's DownloadURL mechanism needs an
// absolute URL).
export function originalUrl(id) {
  return `${window.location.origin}${BASE}/originals/${id}`
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

export async function editPhotoAI(photoId, fields) {
  return request(`/photos/${photoId}/ai`, {
    method: 'PATCH',
    body: JSON.stringify(fields),
  })
}

export async function batchEditAI(payload) {
  return request('/photos/ai/batch', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function pauseAnalysis() {
  return request('/analyze/pause', { method: 'POST' })
}

export async function resumeAnalysis() {
  return request('/analyze/resume', { method: 'POST' })
}

export async function cancelAnalysis() {
  return request('/analyze/cancel', { method: 'POST' })
}

/* ── Rename ── */
export async function renamePhotos(options = {}) {
  return request('/rename', {
    method: 'POST',
    body: JSON.stringify(options),
  })
}

export async function renamePreview(options = {}) {
  return request('/rename/preview', {
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

/* ── 投稿管理（征稿后台，可指向远程云服务器）──
   征稿后端可部署在公网服务器（见 docs/部署到阿里云.md）。桌面 App 跨域远程管理时
   Cookie 不发送，故管理调用一律带 X-Intake-Admin-Token 头鉴权。
   未配置服务器地址时回退同源（本机调试照常）。 */

const INTAKE_SRV_KEY = 'intake_server'   // localStorage: { base, token }

export function getIntakeServer() {
  try {
    return JSON.parse(localStorage.getItem(INTAKE_SRV_KEY)) || { base: '', token: '' }
  } catch {
    return { base: '', token: '' }
  }
}

export function setIntakeServer({ base = '', token = '' }) {
  localStorage.setItem(INTAKE_SRV_KEY, JSON.stringify({
    base: base.trim().replace(/\/+$/, ''),
    token: token.trim(),
  }))
}

// 公网投稿页基址：配置了远程服务器即其地址，否则当前同源
export function intakePublicBase() {
  return getIntakeServer().base || window.location.origin
}

// API 根：远程 → {base}/api；同源 → /api
function intakeApiRoot() {
  const { base } = getIntakeServer()
  return base ? `${base}/api` : BASE
}

function intakeHeaders(extra = {}) {
  const { token } = getIntakeServer()
  const h = { ...extra }
  if (token) h['X-Intake-Admin-Token'] = token
  return h
}

async function intakeFetch(path, options = {}) {
  const res = await fetch(`${intakeApiRoot()}${path}`, {
    ...options,
    headers: intakeHeaders(options.headers || {}),
  })
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    if (res.status === 401) msg = '管理口令不正确，或服务器地址有误'
    try {
      const j = JSON.parse(await res.text())
      msg = (typeof j.detail === 'string' ? j.detail : '') || msg
    } catch { /* ignore */ }
    throw new Error(msg)
  }
  if (res.status === 204) return null
  const ct = res.headers.get('content-type') || ''
  return ct.includes('application/json') ? res.json() : res.text()
}

// 表单提交：application/x-www-form-urlencoded（自动带服务器地址与口令头）
function intakeForm(path, fields = {}) {
  const body = new URLSearchParams()
  for (const [k, v] of Object.entries(fields)) body.set(k, v ?? '')
  return intakeFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  })
}

// 连通性探测：当前「服务器地址 + 管理口令」是否有效
export async function intakePing() {
  return intakeFetch('/intake/admin/ping')
}

// 上传模式（OSS 直传 / 本地直存），用于管线状态展示
export async function intakeOssConfig() {
  return intakeFetch('/intake/oss-config')
}

function bookQuery(book) {
  return book ? `?book=${encodeURIComponent(book)}` : ''
}

export async function intakeBoard(book = '') {
  return intakeFetch(`/intake/admin/submissions${bookQuery(book)}`)
}

export async function intakeCodes(book = '') {
  return intakeFetch(`/intake/admin/codes${bookQuery(book)}`)
}

export async function intakeCreateCode({ name, contact = '', code = '', book = '' }) {
  return intakeForm('/intake/admin/codes', { name, contact, code, book })
}

export async function intakeCreateCodesBatch(names, book = '') {
  return intakeForm('/intake/admin/codes/batch', { names, book })
}

// 导出投稿码花名册 CSV。book 指定书籍；base 为投稿页对外地址（写进链接列）。
export async function intakeExportCsv({ book = '', base = '' } = {}) {
  const qs = new URLSearchParams()
  if (book) qs.set('book', book)
  if (base) qs.set('base', base)
  const url = `${intakeApiRoot()}/intake/admin/export.csv${qs.toString() ? '?' + qs : ''}`
  const res = await fetch(url, { headers: intakeHeaders() })
  if (!res.ok) throw new Error(`导出失败: HTTP ${res.status}`)
  const blob = await res.blob()
  // 从响应头取后端给的中文文件名，取不到则回退
  let name = `投稿码花名册_${new Date().toISOString().slice(0, 10)}.csv`
  const cd = res.headers.get('content-disposition') || ''
  const m = cd.match(/filename\*=UTF-8''([^;]+)/i)
  if (m) { try { name = decodeURIComponent(m[1]) } catch { /* keep fallback */ } }
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 5000)
}

/* ── 书籍项目 ── */
export async function intakeBooks() {
  return intakeFetch('/intake/admin/books')
}

export async function intakeCreateBook({ title, code = '' }) {
  return intakeForm('/intake/admin/books', { title, code })
}

export async function intakeSetBookStatus(code, status) {
  return intakeForm(`/intake/admin/books/${encodeURIComponent(code)}/status`, { status })
}

export async function intakeRenameBook(code, title) {
  return intakeFetch(`/intake/admin/books/${encodeURIComponent(code)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ title }).toString(),
  })
}

export async function intakeDeleteCode(pid) {
  return intakeFetch(`/intake/admin/codes/${pid}`, { method: 'DELETE' })
}

// 开启 / 停止某本书的征稿（open=true 开放，false 停止）
export async function intakeSetBookIntake(code, open) {
  return intakeForm(`/intake/admin/books/${encodeURIComponent(code)}/intake`, { open: open ? 1 : 0 })
}

/* ── 看板下钻：某投稿码的照片列表 ── */
export async function intakeFiles(code) {
  return intakeFetch(`/intake/admin/files?code=${encodeURIComponent(code)}`)
}

// 把 admin/files 返回的 url 解析成可直接用于 <img src> 的地址：
// OSS 模式是预签名绝对地址，原样使用；本地直存是相对路径，拼上服务器地址。
// （本地直存 + 远程带口令的极端组合下 <img> 无法携带鉴权头，属开发期边角，生产走 OSS。）
export function intakeImageSrc(url) {
  if (!url) return ''
  if (/^https?:\/\//i.test(url)) return url
  const base = getIntakeServer().base || ''
  return `${base}${url}`
}

/* ── 照片管理：相册（文件夹） ── */
export async function intakeCollections(book = '') {
  return intakeFetch(`/intake/admin/collections${bookQuery(book)}`)
}

export async function intakeCreateCollection(book, name) {
  return intakeForm('/intake/admin/collections', { book, name })
}

export async function intakeRenameCollection(cid, name) {
  return intakeFetch(`/intake/admin/collections/${cid}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ name }).toString(),
  })
}

export async function intakeDeleteCollection(cid) {
  return intakeFetch(`/intake/admin/collections/${cid}`, { method: 'DELETE' })
}

export async function intakeCollectionFiles(cid) {
  return intakeFetch(`/intake/admin/collections/${cid}/files`)
}

// 把一批照片（file_id 数组）加入 / 移出相册
export async function intakeCollectionAdd(cid, fileIds) {
  return intakeForm(`/intake/admin/collections/${cid}/items`, { file_ids: fileIds.join(',') })
}

export async function intakeCollectionRemove(cid, fileIds) {
  return intakeFetch(`/intake/admin/collections/${cid}/items`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ file_ids: fileIds.join(',') }).toString(),
  })
}

// 整个相册打包 zip 下载（带管理口令头取 blob，再触发浏览器保存）
export async function intakeDownloadCollection(cid, name = '相册') {
  const url = `${intakeApiRoot()}/intake/admin/collections/${cid}/download`
  const res = await fetch(url, { headers: intakeHeaders() })
  if (!res.ok) throw new Error(`下载失败: HTTP ${res.status}`)
  const blob = await res.blob()
  let fname = `${name}.zip`
  const cd = res.headers.get('content-disposition') || ''
  const m = cd.match(/filename\*=UTF-8''([^;]+)/i)
  if (m) { try { fname = decodeURIComponent(m[1]) } catch { /* keep fallback */ } }
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = fname
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 5000)
}

/* ── R2 归档：一键触发 + 状态轮询 ── */
export async function intakeArchive(book) {
  return intakeForm('/intake/admin/archive', { book })
}

export async function intakeArchiveStatus(book = '') {
  const qs = book ? `?book=${encodeURIComponent(book)}` : ''
  return intakeFetch(`/intake/admin/archive/status${qs}`)
}
