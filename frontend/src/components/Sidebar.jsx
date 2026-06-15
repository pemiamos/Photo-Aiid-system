import { useState, useCallback, useEffect, useRef } from 'react'
import { usePhotoStore, usePhotoDispatch, Actions } from '../stores/photoStore'
import * as api from '../services/api'
import './Sidebar.css'

const RENAME_TOKENS = ['[摄影师]', '[地点]', '[类别]', '[标签]', '[日期]', '[相机]', '[序号]']

// Mirror of backend render_template: drop empty tokens and the separator that
// would dangle next to them.
function renderTemplate(template, fields) {
  const re = /\[[^\[\]]+\]/g
  const pieces = []
  let pos = 0, m
  while ((m = re.exec(template)) !== null) {
    if (m.index > pos) pieces.push(['lit', template.slice(pos, m.index)])
    pieces.push(['tok', m[0]])
    pos = m.index + m[0].length
  }
  if (pos < template.length) pieces.push(['lit', template.slice(pos)])

  const out = []
  let haveValue = false, pendingSep = ''
  for (const [kind, text] of pieces) {
    if (kind === 'lit') { pendingSep += text; continue }
    const val = (fields[text] || '').toString().trim()
    if (val) {
      if (haveValue && pendingSep) out.push(pendingSep)
      out.push(val)
      haveValue = true
    }
    pendingSep = ''
  }
  return out.join('').replace(/^[_\-. ]+|[_\-. ]+$/g, '') || '未命名'
}

const ENGINES = [
  { value: 'zhipu',  label: '智谱 GLM' },
  { value: 'claude', label: 'Claude API' },
  { value: 'gemini', label: 'Gemini API' },
  { value: 'ollama', label: 'Ollama 本地' },
  { value: 'clip',   label: 'CLIP 本地' },
]

// Ollama 本地视觉模型预设选项
const OLLAMA_MODELS = [
  'qwen2.5vl:72b',
  'qwen2.5vl:7b',
  'qwen2.5vl:3b',
  'gemma3:12b',
  'llava:13b',
]

export default function Sidebar() {
  const state = usePhotoStore()
  const dispatch = usePhotoDispatch()
  const { photos, tags, settings, engineStatus, stats, activeTag, selectedIds, submitMode } = state

  const [testResult, setTestResult] = useState(null)
  const [scanning, setScanning] = useState(false)
  const [customChip, setCustomChip] = useState('')
  const [ollamaModels, setOllamaModels] = useState(null) // null=未扫描, []=扫描失败/无
  const [ollamaCustom, setOllamaCustom] = useState(false) // 是否手动输入模型名
  const [cancelling, setCancelling] = useState(false)     // 已发出取消请求，等待批次结束
  const dragIdx = useRef(null)

  // 扫描 Ollama 本机已安装模型，填充视觉模型下拉
  useEffect(() => {
    if (settings.engine !== 'ollama' || !settings.ollamaUrl) return
    let cancelled = false
    const url = settings.ollamaUrl.replace(/\/+$/, '') + '/api/tags'
    fetch(url)
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => {
        if (cancelled) return
        const names = (data?.models || []).map(m => m.name).filter(Boolean)
        setOllamaModels(names)
      })
      .catch(() => { if (!cancelled) setOllamaModels([]) })
    return () => { cancelled = true }
  }, [settings.engine, settings.ollamaUrl])

  // Rename template as an ordered list of "_"-joined chips.
  const templateChips = (settings.template || '').split('_').filter(Boolean)
  const setChips = (arr) => updateSetting('template', arr.join('_'))
  const addChip = (tok) => setChips([...templateChips, tok])
  const removeChip = (i) => setChips(templateChips.filter((_, x) => x !== i))
  const moveChip = (to) => {
    const from = dragIdx.current
    if (from == null || from === to) return
    const arr = [...templateChips]
    const [m] = arr.splice(from, 1)
    arr.splice(to, 0, m)
    dragIdx.current = null
    setChips(arr)
  }
  const addCustomChip = () => {
    const v = customChip.trim()
    if (v) { addChip(v); setCustomChip('') }
  }
  const [isDragging, setIsDragging] = useState(false)

  /* ── global drag over preventer to stop page navigation ── */
  useEffect(() => {
    const preventDefault = (e) => {
      // If dropping onto our text input, let the browser handle it natively
      if (e.target.tagName === 'INPUT' && e.target.type === 'text') {
        return
      }
      e.preventDefault()
    }
    window.addEventListener('dragover', preventDefault)
    window.addEventListener('drop', preventDefault)
    return () => {
      window.removeEventListener('dragover', preventDefault)
      window.removeEventListener('drop', preventDefault)
    }
  }, [])

  /* ── settings update helper ── */
  const updateSetting = useCallback((key, value) => {
    dispatch({ type: Actions.SET_SETTINGS, payload: { [key]: value } })
  }, [dispatch])

  /* ── drag & drop handlers ── */
  /* ── scan folder ── */
  const handleScan = useCallback(async (overridePath) => {
    const targetPath = overridePath || settings.folderPath
    if (!targetPath || !targetPath.trim()) return
    setScanning(true)
    dispatch({ type: Actions.SET_SCAN_STATUS, payload: 'scanning' })
    try {
      await api.scanFolder(targetPath.trim())
    } catch (err) {
      dispatch({ type: Actions.SET_ERROR, payload: err.message })
      dispatch({ type: Actions.SET_SCAN_STATUS, payload: 'idle' })
      setScanning(false)
    }
  }, [settings.folderPath, dispatch])

  /* ── drag & drop handlers ── */
  const handleDragOver = useCallback((e) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
  }, [])

  const handleDragEnter = useCallback((e) => {
    e.preventDefault()
    if (e.dataTransfer.types.includes('Files')) {
      setIsDragging(true)
    }
  }, [])

  const handleDragLeave = useCallback(() => {
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback((e) => {
    setIsDragging(false)
    const file = e.dataTransfer.files[0]
    if (file && file.path) {
      e.preventDefault()
      let val = file.path
      // If it's a file, automatically get its parent directory
      if (/\.[a-zA-Z0-9]+$/.test(val)) {
        const lastSlash = Math.max(val.lastIndexOf('/'), val.lastIndexOf('\\'))
        if (lastSlash > 0) {
          val = val.substring(0, lastSlash)
        }
      }
      updateSetting('folderPath', val)
      handleScan(val)
    } else {
      // Standard browser fallback: wait for native text drop insertion
      setTimeout(() => {
        const inputElement = e.target
        if (inputElement && inputElement.value) {
          let val = inputElement.value
          if (val.startsWith('file://')) {
            val = decodeURIComponent(val.replace(/^file:\/\/(localhost)?/, ''))
            if (/^\/[a-zA-Z]:/.test(val)) {
              val = val.substring(1)
            }
          }
          if (/\.[a-zA-Z0-9]+$/.test(val)) {
            const lastSlash = Math.max(val.lastIndexOf('/'), val.lastIndexOf('\\'))
            if (lastSlash > 0) {
              val = val.substring(0, lastSlash)
            }
          }
          inputElement.value = val
          updateSetting('folderPath', val)
          handleScan(val)
        }
      }, 100)
    }
  }, [updateSetting, handleScan])

  /* ── native folder select dialog ── */
  const handleBrowse = useCallback(async () => {
    try {
      const data = await api.selectFolder()
      if (data && data.folder_path) {
        updateSetting('folderPath', data.folder_path)
        handleScan(data.folder_path)
      }
    } catch (err) {
      dispatch({ type: Actions.SET_ERROR, payload: err.message })
    }
  }, [updateSetting, handleScan, dispatch])

  // Auto-sync settings to backend with a 1-second debounce
  useEffect(() => {
    const timer = setTimeout(async () => {
      try {
        await api.updateSettings({
          engine: settings.engine,
          claude_api_key: settings.apiKey,
          gemini_api_key: settings.geminiApiKey,
          gemini_model: settings.geminiModel,
          ollama_url: settings.ollamaUrl,
          ollama_model: settings.ollamaModel,
          rename_prefix: settings.prefix,
          rename_template: settings.template,
        })
      } catch (err) {
        console.error("Auto-syncing settings failed:", err)
      }
    }, 1000)
    return () => clearTimeout(timer)
  }, [settings])

  // Poll scan progress and photos in real-time when scanStatus is 'scanning'
  useEffect(() => {
    if (state.scanStatus !== 'scanning') return

    setScanning(true)

    // The backend scan runs as a background task, so the first few polls may see
    // running=false before scan_directory flips the global progress flag. This
    // gap is wider on Windows (slower process/IO startup, os.walk). Don't declare
    // the scan "finished" until we've actually observed running=true at least
    // once — otherwise the very first poll races the scan start and prematurely
    // flips to 'done' with zero photos, leaving the gallery empty until the app
    // is restarted. A startup grace window avoids getting stuck if the scan never
    // starts. (Mirrors the analysis-polling guard below.)
    let sawRunning = false
    const startedAt = Date.now()
    const STARTUP_GRACE_MS = 8000

    const fetchProgressAndPhotos = async () => {
      try {
        const progress = await api.getScanProgress()

        // Load scanned photos in real-time
        const photoRes = await api.getPhotos({ folder_path: settings.folderPath })
        if (photoRes && photoRes.photos) {
          dispatch({ type: Actions.SET_PHOTOS, payload: photoRes.photos })
        }

        if (progress && progress.running) {
          sawRunning = true
        } else if (sawRunning || Date.now() - startedAt > STARTUP_GRACE_MS) {
          // Either the scan ran and is now done, or it never started within the
          // grace window — finish up.
          dispatch({ type: Actions.SET_SCAN_STATUS, payload: 'done' })
          setScanning(false)
        }
        // else: scan not started yet, keep polling within the grace window
      } catch (err) {
        console.error("Polling scan progress failed:", err)
      }
    }

    // Trigger immediately
    fetchProgressAndPhotos()

    const intervalId = setInterval(fetchProgressAndPhotos, 1000)
    return () => clearInterval(intervalId)
  }, [state.scanStatus, settings.folderPath, dispatch])

  // Poll analysis progress and photos in real-time when engineStatus is 'busy'
  useEffect(() => {
    if (state.engineStatus !== 'busy') return

    // The backend batch starts asynchronously, so the first few polls may see
    // running=false before it spins up. Don't declare "finished" until we've
    // actually observed running=true at least once — otherwise the very first
    // poll races the batch start and prematurely flips back to 'done' (which
    // made analysis appear to need two clicks). A startup grace window avoids
    // getting stuck busy if the batch never starts.
    let sawRunning = false
    const startedAt = Date.now()
    const STARTUP_GRACE_MS = 8000

    const fetchAnalysisProgressAndPhotos = async () => {
      try {
        const progress = await api.getAnalysisProgress()
        if (!progress) return

        if (progress.running) {
          sawRunning = true
          dispatch({
            type: Actions.SET_ANALYSIS_PROGRESS,
            payload: {
              current: progress.completed,
              total: progress.total,
              elapsed: progress.elapsed_seconds,
              eta: progress.eta_seconds,
              paused: progress.paused,
            }
          })
          // Poll photos to update cards dynamically
          const photoRes = await api.getPhotos({ folder_path: settings.folderPath })
          if (photoRes && photoRes.photos) {
            dispatch({ type: Actions.SET_PHOTOS, payload: photoRes.photos })
          }
          // Update tags
          const tagsList = await api.getTags()
          dispatch({ type: Actions.SET_TAGS, payload: tagsList })
        } else if (sawRunning || Date.now() - startedAt > STARTUP_GRACE_MS) {
          // Either the batch ran and is now done, or it never started within
          // the grace window — finish up and refresh once.
          dispatch({ type: Actions.SET_ENGINE_STATUS, payload: 'done' })
          dispatch({ type: Actions.SET_ANALYSIS_PROGRESS, payload: null })
          const photoRes = await api.getPhotos({ folder_path: settings.folderPath })
          if (photoRes && photoRes.photos) {
            dispatch({ type: Actions.SET_PHOTOS, payload: photoRes.photos })
          }
          const tagsList = await api.getTags()
          dispatch({ type: Actions.SET_TAGS, payload: tagsList })
        }
        // else: batch not started yet, keep waiting within the grace window
      } catch (err) {
        console.error("Polling analysis progress failed:", err)
      }
    }

    // Trigger immediately
    fetchAnalysisProgressAndPhotos()

    const intervalId = setInterval(fetchAnalysisProgressAndPhotos, 1000)
    return () => clearInterval(intervalId)
  }, [state.engineStatus, settings.folderPath, dispatch])

  /* ── filter photos by current folder path ── */
  const normalizePath = (p) => p ? p.normalize('NFC').replace(/\\/g, '/').replace(/\/$/, '') : ''
  const currentFolder = normalizePath(settings.folderPath)
  const folderPhotos = currentFolder
    ? photos.filter(p => p.file_path && normalizePath(p.file_path).startsWith(currentFolder))
    : photos

  // Live rename preview using the first analyzed photo in the folder.
  const previewPhoto = folderPhotos.find(p => p.ai)
  let renamePreview = ''
  if (previewPhoto) {
    const ai = previewPhoto.ai || {}
    const exif = previewPhoto.exif || {}
    const date = (exif.date_time_original || '').replace(/[-:]/g, '').split(' ')[0].slice(0, 8)
    const tags = ai.tags || []
    const ext = (previewPhoto.file_name.match(/\.[a-zA-Z0-9]+$/) || ['.jpg'])[0]
    renamePreview = renderTemplate(settings.template || '', {
      '[前缀]': settings.prefix,
      '[摄影师]': ai.photographer,
      '[地点]': ai.location,
      '[类别]': ai.category,
      '[标签]': tags[0] || '',
      '[日期]': date,
      '[相机]': exif.camera_model,
      '[序号]': '001',
    }) + ext
  }

  /* ── analyze (shared runner) ── */
  const runAnalysis = useCallback(async (photoIds) => {
    if (!photoIds || photoIds.length === 0) return
    dispatch({ type: Actions.SET_ENGINE_STATUS, payload: 'busy' })
    dispatch({ type: Actions.SET_ANALYSIS_PROGRESS, payload: { current: 0, total: photoIds.length } })
    try {
      // Sync settings to backend first to ensure keys/model are stored
      await api.updateSettings({
        engine: settings.engine,
        claude_api_key: settings.apiKey,
        gemini_api_key: settings.geminiApiKey,
        gemini_model: settings.geminiModel,
        zhipu_api_key: settings.zhipuApiKey,
        ollama_url: settings.ollamaUrl,
        ollama_model: settings.ollamaModel,
        rename_prefix: settings.prefix,
        rename_template: settings.template,
      })

      await api.analyzePhotos({
        photo_ids: photoIds,
        engine: settings.engine,
        concurrency: 1, // Gemini/Claude is serialized to avoid rate-limiting, Ollama/CLIP is concurrency controlled by backend
      })
    } catch (err) {
      dispatch({ type: Actions.SET_ERROR, payload: err.message })
      dispatch({ type: Actions.SET_ENGINE_STATUS, payload: 'error' })
      dispatch({ type: Actions.SET_ANALYSIS_PROGRESS, payload: null })
    }
  }, [settings, dispatch])

  /* ── 全局分析：整个文件夹中尚未分析（待分析/失败）的照片 ── */
  const handleAnalyzeAll = useCallback(async () => {
    const targets = folderPhotos.filter(p => p.scan_status === 'queued' || p.scan_status === 'error')
    if (targets.length === 0) {
      alert("当前文件夹没有需要分析的照片（均已分析完成）。")
      return
    }
    await runAnalysis(targets.map(p => p.id))
  }, [folderPhotos, runAnalysis])

  /* ── 自选分析：强制重新分析用户点选的全部照片（含已分析完成的） ── */
  const handleAnalyzeSelected = useCallback(async () => {
    if (selectedIds.length === 0) {
      alert("请先在画廊中点选要分析的照片，再点「自选分析」。")
      return
    }
    const selectedSet = new Set(selectedIds)
    const targets = folderPhotos.filter(p => selectedSet.has(p.id))
    if (targets.length === 0) return
    await runAnalysis(targets.map(p => p.id))
  }, [selectedIds, folderPhotos, runAnalysis])

  /* ── clear ── */
  const handleClear = useCallback(() => {
    dispatch({ type: Actions.CLEAR_ALL })
    setTestResult(null)
  }, [dispatch])

  /* ── cancel running analysis ── */
  const handleCancel = useCallback(async () => {
    setCancelling(true)
    try {
      await api.cancelAnalysis()
    } catch (err) {
      dispatch({ type: Actions.SET_ERROR, payload: err.message })
      setCancelling(false)
    }
  }, [dispatch])

  // Clear the "cancelling" flag once the batch is no longer running.
  useEffect(() => {
    if (engineStatus !== 'busy') setCancelling(false)
  }, [engineStatus])

  /* ── test connection ── */
  const handleTest = useCallback(async () => {
    setTestResult({ status: 'testing', message: '测试中…' })
    try {
      const data = await api.healthCheck()
      setTestResult({ status: 'success', message: `✓ 后端连接正常\n引擎: ${data?.engine || settings.engine}` })
    } catch (err) {
      setTestResult({ status: 'error', message: `✗ 连接失败: ${err.message}` })
    }
  }, [settings.engine])

  /* ── collect all tags from folder photos ── */
  const allTags = []
  const tagSet = new Set()
  folderPhotos.forEach(p => {
    if (p.ai_tags) {
      const tags = Array.isArray(p.ai_tags) ? p.ai_tags : [p.ai_tags]
      tags.forEach(t => {
        if (!tagSet.has(t)) {
          tagSet.add(t)
          allTags.push(t)
        }
      })
    }
    if (p.ai_category && !tagSet.has(p.ai_category)) {
      tagSet.add(p.ai_category)
      allTags.push(p.ai_category)
    }
  })

  const analyzedCount = folderPhotos.filter(p => p.status === 'done' || p.ai_tags).length
  const renamedCount = folderPhotos.filter(p => p.renamed).length

  return (
    <aside className="sidebar">
      {/* 投稿模式下，整块编辑功能锁定变灰 */}
      <div className={`sidebar-edit${submitMode ? ' locked' : ''}`}
        aria-disabled={submitMode}>
      {/* ── 链接照片 ── */}
      <div className="sidebar-section">
        <h3>链接照片</h3>
        <div className={`folder-input-row ${isDragging ? 'dragging' : ''}`}>
          <input
            type="text"
            placeholder={isDragging ? "释放以填入路径" : "文件夹路径，如 /Users/photos"}
            value={settings.folderPath}
            onChange={e => {
              let val = e.target.value
              // Clean file:// prefix if pasted/inserted natively
              if (val.startsWith('file://')) {
                val = decodeURIComponent(val.replace(/^file:\/\/(localhost)?/, ''))
                if (/^\/[a-zA-Z]:/.test(val)) {
                  val = val.substring(1)
                }
              }
              // Extract containing folder if user drags in a file instead of a folder
              if (/\.[a-zA-Z0-9]+$/.test(val)) {
                const lastSlash = Math.max(val.lastIndexOf('/'), val.lastIndexOf('\\'))
                if (lastSlash > 0) {
                  val = val.substring(0, lastSlash)
                }
              }
              updateSetting('folderPath', val)
            }}
            onKeyDown={e => e.key === 'Enter' && handleScan()}
            onDragOver={handleDragOver}
            onDragEnter={handleDragEnter}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          />
          <button
            type="button"
            className="btn ghost browse-btn"
            onClick={handleBrowse}
            title="选择本地文件夹"
            disabled={scanning}
          >
            {scanning ? '扫描中…' : '浏览'}
          </button>
        </div>
        <div className="sidebar-hint">
          {scanning ? (
            <span className="scanning-pulse">⏳ 正在智能扫描并建立索引…</span>
          ) : (
            "非侵入 · 不复制不上传，仅建立索引"
          )}
        </div>
      </div>

      {/* ── 识别引擎 ── */}
      <div className="sidebar-section">
        <h3>识别引擎</h3>
        <select
          value={settings.engine}
          onChange={e => updateSetting('engine', e.target.value)}
        >
          {ENGINES.map(e => (
            <option key={e.value} value={e.value}>{e.label}</option>
          ))}
        </select>

        {settings.engine === 'zhipu' && (
          <div className="engine-config">
            <label className="sidebar-field">API Key</label>
            <input
              type="password"
              placeholder="xxxxxxxx.xxxxxxxx"
              value={settings.zhipuApiKey || ''}
              onChange={e => updateSetting('zhipuApiKey', e.target.value)}
            />
            <div className="sidebar-hint">
              默认 glm-4v-flash（免费视觉模型）
              <br />
              <a href="https://open.bigmodel.cn/usercenter/apikeys" target="_blank" rel="noreferrer" style={{color:'var(--amber)'}}>
                open.bigmodel.cn
              </a>
              {' '}获取 Key
            </div>
          </div>
        )}

        {settings.engine === 'claude' && (
          <div className="engine-config">
            <label className="sidebar-field">API Key</label>
            <input
              type="password"
              placeholder="sk-ant-…"
              value={settings.apiKey}
              onChange={e => updateSetting('apiKey', e.target.value)}
            />
            <div className="sidebar-hint">
              console.anthropic.com 获取，仅存于本机
            </div>
          </div>
        )}

        {settings.engine === 'gemini' && (
          <div className="engine-config">
            <label className="sidebar-field">API Key</label>
            <input
              type="password"
              placeholder="AIza…"
              value={settings.geminiApiKey || ''}
              onChange={e => updateSetting('geminiApiKey', e.target.value)}
            />
            <div className="sidebar-hint">
              默认使用 gemini-2.5-flash
              <br />
              <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer" style={{color:'var(--amber)'}}>
                aistudio.google.com/apikey
              </a>
              {' '}获取 Key
            </div>
          </div>
        )}

        {settings.engine === 'ollama' && (
          <div className="engine-config">
            <label className="sidebar-field">Endpoint</label>
            <input
              type="text"
              value={settings.ollamaUrl}
              onChange={e => updateSetting('ollamaUrl', e.target.value)}
            />
            <label className="sidebar-field">
              视觉模型
              {ollamaModels === null
                ? <span className="sidebar-hint" style={{marginLeft:8}}>扫描中…</span>
                : <span className="sidebar-hint" style={{marginLeft:8}}>已安装 {ollamaModels.length} 个</span>}
            </label>
            {(() => {
              const installed = ollamaModels && ollamaModels.length ? ollamaModels : OLLAMA_MODELS
              const isCustom = ollamaCustom || !installed.includes(settings.ollamaModel)
              return (
                <>
                  <select
                    value={isCustom ? '__custom__' : settings.ollamaModel}
                    onChange={e => {
                      if (e.target.value === '__custom__') {
                        setOllamaCustom(true)
                      } else {
                        setOllamaCustom(false)
                        updateSetting('ollamaModel', e.target.value)
                      }
                    }}
                  >
                    {installed.map(m => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                    <option value="__custom__">自定义…</option>
                  </select>
                  {isCustom && (
                    <input
                      type="text"
                      autoFocus
                      placeholder="输入模型名，如 qwen2.5vl:7b"
                      value={settings.ollamaModel}
                      onChange={e => updateSetting('ollamaModel', e.target.value)}
                    />
                  )}
                </>
              )
            })()}
            <div className="sidebar-hint">
              需先允许浏览器跨域访问 Ollama：
              <br />launchctl setenv OLLAMA_ORIGINS "*"
              <br />然后重启 Ollama 服务
            </div>
          </div>
        )}

        {settings.engine === 'clip' && (
          <div className="engine-config">
            <div className="sidebar-hint good">
              CLIP 本地推理，无需额外配置
            </div>
          </div>
        )}
      </div>

      {/* ── 重命名模板 ── */}
      <div className="sidebar-section">
        <h3>重命名模板</h3>
        <label className="sidebar-field">拖动排序，× 删除</label>
        <div className="tpl-builder">
          {templateChips.length === 0 && (
            <span className="tpl-empty">从下方添加字段块…</span>
          )}
          {templateChips.map((chip, i) => (
            <span
              key={`${chip}-${i}`}
              className="tpl-chip"
              draggable
              onDragStart={() => { dragIdx.current = i }}
              onDragOver={e => e.preventDefault()}
              onDrop={() => moveChip(i)}
            >
              {chip}
              <button className="tpl-x" onClick={() => removeChip(i)}>×</button>
            </span>
          ))}
        </div>

        <label className="sidebar-field">可添加字段</label>
        <div className="token-chips">
          {RENAME_TOKENS.map(t => (
            <button key={t} type="button" className="token-chip"
              title="添加到模板" onClick={() => addChip(t)}>
              {t}
            </button>
          ))}
        </div>

        <div className="tpl-custom">
          <input
            type="text"
            placeholder="自定义块，如 [活动] 或 婚礼"
            value={customChip}
            onChange={e => setCustomChip(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') addCustomChip() }}
          />
          <button className="token-chip" onClick={addCustomChip}>添加</button>
        </div>

        {renamePreview && (
          <div className="rename-preview">
            预览：<span>{renamePreview}</span>
          </div>
        )}
        <div className="sidebar-hint">
          空字段自动省略，重名自动加 -2/-3 后缀
        </div>
      </div>

      {/* ── 标签过滤 ── */}
      <div className="sidebar-section">
        <h3>标签过滤</h3>
        <div className="tag-chips">
          {allTags.length === 0 ? (
            <span className="sidebar-hint">分析完成后出现</span>
          ) : (
            allTags.slice(0, 24).map(tag => (
              <button
                key={tag}
                className={`tag-chip${activeTag === tag ? ' active' : ''}`}
                onClick={() => dispatch({
                  type: Actions.SET_ACTIVE_TAG,
                  payload: activeTag === tag ? null : tag,
                })}
              >
                {tag}
              </button>
            ))
          )}
        </div>
      </div>

      {/* ── 库统计 ── */}
      <div className="sidebar-section">
        <h3>库统计</h3>
        <div className="stat-row"><span>照片</span><b>{folderPhotos.length}</b></div>
        <div className="stat-row"><span>已分析</span><b>{analyzedCount}</b></div>
        <div className="stat-row"><span>标签数</span><b>{allTags.length}</b></div>
        <div className="stat-row"><span>已重命名</span><b>{renamedCount}</b></div>
      </div>

      {/* ── actions ── */}
      <div className="sidebar-section">
        <button
          className="btn primary"
          onClick={handleAnalyzeAll}
          disabled={folderPhotos.length === 0 || engineStatus === 'busy'}
          title="分析整个文件夹中尚未分析的照片"
        >
          {engineStatus === 'busy' ? '分析中…' : '全局分析'}
        </button>
        <button
          className="btn primary"
          onClick={handleAnalyzeSelected}
          disabled={selectedIds.length === 0 || engineStatus === 'busy'}
          title="仅分析在画廊中点选的照片"
        >
          {engineStatus === 'busy'
            ? '分析中…'
            : `自选分析${selectedIds.length ? ` (${selectedIds.length})` : ''}`}
        </button>
        {engineStatus === 'busy' ? (
          <button
            className="btn danger"
            onClick={handleCancel}
            disabled={cancelling}
            title="中断并取消正在进行的 AI 分析"
          >
            {cancelling ? '正在取消…' : '取消任务'}
          </button>
        ) : (
          <button
            className="btn ghost"
            onClick={handleClear}
            disabled={folderPhotos.length === 0}
          >
            清空
          </button>
        )}
        <button className="btn ghost" onClick={handleTest}>
          测试连接
        </button>
        {testResult && (
          <div className={`test-result ${testResult.status}`}>
            {testResult.message}
          </div>
        )}
      </div>
      </div>{/* /.sidebar-edit */}

      {/* ── 投稿接口（模式开关，下沉紧贴底部横线） ── */}
      <div className="sidebar-section submit-toggle">
        <button
          className={`btn ${submitMode ? 'primary' : 'ghost'}`}
          onClick={() => dispatch({ type: Actions.SET_SUBMIT_MODE, payload: !submitMode })}
          title="进入/退出投稿模式：在画廊里勾选要投稿的照片后确认提交"
        >
          {submitMode ? '退出投稿模式' : '投稿接口'}
        </button>
      </div>

      <footer className="sidebar-footer">
        <img className="footer-logo" src="/logo.png" alt="星尘远征队" />
        <div className="footer-text">
          <a
            href="https://creativecommons.org/licenses/by-nc-sa/4.0/deed.zh"
            target="_blank"
            rel="noreferrer"
          >
            CC BY-NC-SA 4.0
          </a>
          <span className="footer-credit">星尘远征队 出品</span>
        </div>
      </footer>
    </aside>
  )
}
