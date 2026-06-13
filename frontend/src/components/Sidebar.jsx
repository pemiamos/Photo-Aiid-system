import { useState, useCallback, useEffect } from 'react'
import { usePhotoStore, usePhotoDispatch, Actions } from '../stores/photoStore'
import * as api from '../services/api'
import './Sidebar.css'

const ENGINES = [
  { value: 'claude', label: 'Claude API' },
  { value: 'gemini', label: 'Gemini API' },
  { value: 'ollama', label: 'Ollama 本地' },
  { value: 'clip',   label: 'CLIP 本地' },
]

export default function Sidebar() {
  const state = usePhotoStore()
  const dispatch = usePhotoDispatch()
  const { photos, tags, settings, engineStatus, stats, activeTag } = state

  const [testResult, setTestResult] = useState(null)
  const [scanning, setScanning] = useState(false)
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

    const fetchProgressAndPhotos = async () => {
      try {
        const progress = await api.getScanProgress()
        
        // Load scanned photos in real-time
        const photoRes = await api.getPhotos({ folder_path: settings.folderPath })
        if (photoRes && photoRes.photos) {
          dispatch({ type: Actions.SET_PHOTOS, payload: photoRes.photos })
        }

        if (progress && !progress.running) {
          dispatch({ type: Actions.SET_SCAN_STATUS, payload: 'done' })
          setScanning(false)
        }
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

    const fetchAnalysisProgressAndPhotos = async () => {
      try {
        const progress = await api.getAnalysisProgress()
        if (progress) {
          if (progress.running) {
            dispatch({
              type: Actions.SET_ANALYSIS_PROGRESS,
              payload: { current: progress.completed, total: progress.total }
            })
            // Poll photos to update cards dynamically
            const photoRes = await api.getPhotos({ folder_path: settings.folderPath })
            if (photoRes && photoRes.photos) {
              dispatch({ type: Actions.SET_PHOTOS, payload: photoRes.photos })
            }
            // Update tags
            const tagsList = await api.getTags()
            dispatch({ type: Actions.SET_TAGS, payload: tagsList })
          } else {
            // Background analysis finished
            dispatch({ type: Actions.SET_ENGINE_STATUS, payload: 'done' })
            dispatch({ type: Actions.SET_ANALYSIS_PROGRESS, payload: null })
            // Final refresh
            const photoRes = await api.getPhotos({ folder_path: settings.folderPath })
            if (photoRes && photoRes.photos) {
              dispatch({ type: Actions.SET_PHOTOS, payload: photoRes.photos })
            }
            const tagsList = await api.getTags()
            dispatch({ type: Actions.SET_TAGS, payload: tagsList })
          }
        }
      } catch (err) {
        console.error("Polling analysis progress failed:", err)
      }
    }

    // Trigger immediately
    fetchAnalysisProgressAndPhotos()

    const intervalId = setInterval(fetchAnalysisProgressAndPhotos, 1000)
    return () => clearInterval(intervalId)
  }, [state.engineStatus, settings.folderPath, dispatch])

  /* ── analyze ── */
  const handleAnalyze = useCallback(async () => {
    // Filter photos to only those that are currently displayed and in queued/error status
    const targets = photos.filter(p => p.scan_status === 'queued' || p.scan_status === 'error')
    if (targets.length === 0) {
      alert("当前展示的图片中没有需要分析的照片（均已分析完成）。")
      return
    }

    dispatch({ type: Actions.SET_ENGINE_STATUS, payload: 'busy' })
    dispatch({ type: Actions.SET_ANALYSIS_PROGRESS, payload: { current: 0, total: targets.length } })
    try {
      // Sync settings to backend first to ensure keys/model are stored
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

      await api.analyzePhotos({
        photo_ids: targets.map(p => p.id),
        engine: settings.engine,
        concurrency: 1, // Gemini/Claude is serialized to avoid rate-limiting, Ollama/CLIP is concurrency controlled by backend
      })
    } catch (err) {
      dispatch({ type: Actions.SET_ERROR, payload: err.message })
      dispatch({ type: Actions.SET_ENGINE_STATUS, payload: 'error' })
      dispatch({ type: Actions.SET_ANALYSIS_PROGRESS, payload: null })
    }
  }, [photos, settings, dispatch])

  /* ── clear ── */
  const handleClear = useCallback(() => {
    dispatch({ type: Actions.CLEAR_ALL })
    setTestResult(null)
  }, [dispatch])

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

  /* ── filter photos by current folder path ── */
  const normalizePath = (p) => p ? p.normalize('NFC').replace(/\\/g, '/').replace(/\/$/, '') : ''
  const currentFolder = normalizePath(settings.folderPath)
  const folderPhotos = currentFolder
    ? photos.filter(p => p.file_path && normalizePath(p.file_path).startsWith(currentFolder))
    : photos

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
            <label className="sidebar-field">模型</label>
            <input
              type="text"
              value={settings.geminiModel || 'gemini-2.5-flash'}
              onChange={e => updateSetting('geminiModel', e.target.value)}
            />
            <div className="sidebar-hint">
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
            <label className="sidebar-field">视觉模型</label>
            <input
              type="text"
              value={settings.ollamaModel}
              onChange={e => updateSetting('ollamaModel', e.target.value)}
            />
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
        <label className="sidebar-field">前缀</label>
        <input
          type="text"
          value={settings.prefix}
          onChange={e => updateSetting('prefix', e.target.value)}
        />
        <label className="sidebar-field">模板</label>
        <input
          type="text"
          value={settings.template}
          onChange={e => updateSetting('template', e.target.value)}
        />
        <div className="sidebar-hint">
          占位符：[前缀] [AI标签] [日期] [序号]
          <br />重名自动加 -2/-3 后缀
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
          onClick={handleAnalyze}
          disabled={folderPhotos.length === 0 || engineStatus === 'busy'}
        >
          {engineStatus === 'busy' ? '分析中…' : '开始 AI 分析'}
        </button>
        <button
          className="btn ghost"
          onClick={handleClear}
          disabled={folderPhotos.length === 0}
        >
          清空
        </button>
        <button className="btn ghost" onClick={handleTest}>
          测试连接
        </button>
        {testResult && (
          <div className={`test-result ${testResult.status}`}>
            {testResult.message}
          </div>
        )}
      </div>
    </aside>
  )
}
