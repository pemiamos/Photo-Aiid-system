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
  { value: 'openai', label: 'OpenAI API' },
  { value: 'ollama', label: 'Ollama 本地' },
  { value: 'clip',   label: 'CLIP 本地' },
]

// OpenAI 视觉模型预设（均支持 chat/completions + 图片输入）。
// 价格/能力从低到高：4o-mini ≈ 4.1-mini < 4.1 < 4o；按需挑，也可「自定义…」填任意模型名。
const OPENAI_MODELS = [
  'gpt-4o-mini',
  'gpt-4.1-mini',
  'gpt-4.1',
  'gpt-4o',
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
  const { photos, tags, settings, engineStatus, stats, activeTag, selectedIds, submitMode, proMode } = state

  const [testResult, setTestResult] = useState(null)
  const [scanning, setScanning] = useState(false)
  const [customChip, setCustomChip] = useState('')
  const [ollamaModels, setOllamaModels] = useState(null) // null=未扫描, []=扫描失败/无
  const [ollamaCustom, setOllamaCustom] = useState(false) // 是否手动输入模型名
  const [openaiCustom, setOpenaiCustom] = useState(false) // OpenAI 模型是否手动输入
  const [openaiModels, setOpenaiModels] = useState(null)  // null=拉取中, []=失败/未配置
  const [cancelling, setCancelling] = useState(false)     // 已发出取消请求，等待批次结束
  const [dragChip, setDragChip] = useState(null)          // 正在拖拽的字段块索引（用于高亮）

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

  // 拉取 OpenAI（或兼容网关）实际支持的模型，填充下拉。读取后端已保存的 key/base，
  // 所以手动刷新前最好等设置自动同步（~1s）落库；提供「↻」按钮可随时重拉。
  const fetchOpenaiModels = useCallback(async () => {
    setOpenaiModels(null)
    try {
      const d = await api.openaiModels()
      setOpenaiModels(d?.ok ? (d.models || []) : [])
    } catch {
      setOpenaiModels([])
    }
  }, [])
  useEffect(() => {
    if (settings.engine !== 'openai') return
    fetchOpenaiModels()
  }, [settings.engine, fetchOpenaiModels])

  // Rename template as an ordered list of "_"-joined chips.
  const templateChips = (settings.template || '').split('_').filter(Boolean)
  const setChips = (arr) => updateSetting('template', arr.join('_'))
  const addChip = (tok) => setChips([...templateChips, tok])
  const removeChip = (i) => setChips(templateChips.filter((_, x) => x !== i))

  /* ── 字段块拖拽排序（基于鼠标指针，不用 HTML5 draggable）──
     原因：Tauri 打包后 webview 接管 OS 级拖放，会吞掉页面内 HTML5 拖拽事件，
     导致 draggable 在桌面 App 里失效。改用 mousedown/mousemove/mouseup 自己实现，
     浏览器与桌面 App 都能拖。 */
  const chipDrag = useRef({ active: false, from: null, moved: false, startX: 0, startY: 0 })

  const onChipMouseMove = useCallback((e) => {
    const st = chipDrag.current
    if (!st.active) return
    if (!st.moved &&
        Math.abs(e.clientX - st.startX) < 5 &&
        Math.abs(e.clientY - st.startY) < 5) return  // 阈值：区分点击与拖拽
    st.moved = true
    e.preventDefault()
    const el = document.elementFromPoint(e.clientX, e.clientY)
    const overAttr = el?.closest('.tpl-chip')?.getAttribute('data-idx')
    if (overAttr == null) return
    const to = Number(overAttr)
    if (Number.isNaN(to) || to === st.from) return
    setChips(((arr) => {
      const next = [...arr]
      const [m] = next.splice(st.from, 1)
      next.splice(to, 0, m)
      return next
    })(templateChips))
    st.from = to
    setDragChip(to)
  }, [templateChips, setChips])

  const onChipMouseUp = useCallback(() => {
    window.removeEventListener('mousemove', onChipMouseMove)
    window.removeEventListener('mouseup', onChipMouseUp)
    chipDrag.current = { active: false, from: null, moved: false, startX: 0, startY: 0 }
    setDragChip(null)
  }, [onChipMouseMove])

  const onChipMouseDown = (e, i) => {
    if (e.button !== 0) return                  // 仅左键
    if (e.target.closest('.tpl-x')) return      // 点在「×」删除按钮上不触发
    chipDrag.current = { active: true, from: i, moved: false, startX: e.clientX, startY: e.clientY }
    setDragChip(i)
    window.addEventListener('mousemove', onChipMouseMove)
    window.addEventListener('mouseup', onChipMouseUp)
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
          zhipu_api_key: settings.zhipuApiKey,
          openai_api_key: settings.openaiApiKey,
          openai_model: settings.openaiModel,
          openai_base_url: settings.openaiBaseUrl,
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
        const photoRes = await api.getAllPhotos({ folder_path: settings.folderPath })
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
          const photoRes = await api.getAllPhotos({ folder_path: settings.folderPath })
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
          const photoRes = await api.getAllPhotos({ folder_path: settings.folderPath })
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
        openai_api_key: settings.openaiApiKey,
        openai_model: settings.openaiModel,
        openai_base_url: settings.openaiBaseUrl,
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

  /* ── 全局分析：可对整个文件夹反复重新分析 ──
     · 全新文件夹 → 直接分析全部未分析照片
     · 混合（部分已分析）→ 询问「重分析全部 / 仅补未分析」
     · 全部已分析 → 确认后覆盖式重新分析全部
     已分析照片会被重新调用 AI 并覆盖原结果（含摄影师/地点/标签）。*/
  const handleAnalyzeAll = useCallback(async () => {
    if (folderPhotos.length === 0) {
      alert("当前文件夹没有照片。")
      return
    }
    const isAnalyzed = p => p.scan_status === 'done' || !!p.ai
    const pending = folderPhotos.filter(p => !isAnalyzed(p))
    const analyzedNum = folderPhotos.length - pending.length

    let targets
    if (pending.length === 0) {
      // 全部已分析：确认是否覆盖重跑
      if (!confirm(`文件夹内 ${folderPhotos.length} 张照片均已分析。\n是否重新分析全部（覆盖已有结果）？`)) return
      targets = folderPhotos
    } else if (analyzedNum > 0) {
      // 混合：让用户选择重分析全部还是仅补未分析
      const reAll = confirm(
        `文件夹共 ${folderPhotos.length} 张，其中 ${analyzedNum} 张已分析。\n\n` +
        `「确定」= 重新分析全部 ${folderPhotos.length} 张（覆盖已有结果）\n` +
        `「取消」= 仅分析未分析的 ${pending.length} 张`
      )
      targets = reAll ? folderPhotos : pending
    } else {
      // 全新文件夹：分析全部
      targets = folderPhotos
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
  // 标签/类别在照片对象上是嵌套的 p.ai.{tags,category}（见 /api/photos 返回），
  // 不是顶层 p.ai_tags/p.ai_category——之前用错字段导致「标签数」恒为 0。
  const allTags = []
  const tagSet = new Set()
  folderPhotos.forEach(p => {
    const ai = p.ai
    if (!ai) return
    const tags = Array.isArray(ai.tags) ? ai.tags : (ai.tags ? [ai.tags] : [])
    tags.forEach(t => {
      if (t && !tagSet.has(t)) {
        tagSet.add(t)
        allTags.push(t)
      }
    })
    if (ai.category && !tagSet.has(ai.category)) {
      tagSet.add(ai.category)
      allTags.push(ai.category)
    }
  })

  // 已分析 = 扫描状态为 done 或已有 ai 结果（之前用的 p.status/p.ai_tags 字段不存在）。
  const analyzedCount = folderPhotos.filter(p => p.scan_status === 'done' || p.ai).length
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

        {settings.engine === 'openai' && (
          <div className="engine-config">
            <label className="sidebar-field">API Key</label>
            <input
              type="password"
              placeholder="sk-…"
              value={settings.openaiApiKey || ''}
              onChange={e => updateSetting('openaiApiKey', e.target.value)}
            />
            <label className="sidebar-field">API 地址（可选）</label>
            <input
              type="text"
              placeholder="https://api.openai.com/v1"
              value={settings.openaiBaseUrl || ''}
              onChange={e => updateSetting('openaiBaseUrl', e.target.value)}
            />
            <label className="sidebar-field">
              模型
              {openaiModels === null
                ? <span className="sidebar-hint" style={{marginLeft:8}}>拉取中…</span>
                : openaiModels.length
                  ? <span className="sidebar-hint" style={{marginLeft:8}}>接口可用 {openaiModels.length} 个</span>
                  : <span className="sidebar-hint" style={{marginLeft:8}}>未拉到（填好 Key/地址后点 ↻）</span>}
              <button
                type="button"
                className="link-btn"
                style={{marginLeft:8}}
                title="重新从接口拉取可用模型"
                onClick={fetchOpenaiModels}
              >↻ 刷新</button>
            </label>
            {(() => {
              // 优先用接口实拉的列表；拉不到时退回少量常见预设，仍可「自定义…」手填
              const available = (openaiModels && openaiModels.length) ? openaiModels : OPENAI_MODELS
              const isCustom = openaiCustom || !available.includes(settings.openaiModel)
              return (
                <>
                  <select
                    value={isCustom ? '__custom__' : settings.openaiModel}
                    onChange={e => {
                      if (e.target.value === '__custom__') {
                        setOpenaiCustom(true)
                      } else {
                        setOpenaiCustom(false)
                        updateSetting('openaiModel', e.target.value)
                      }
                    }}
                  >
                    {available.map(m => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                    <option value="__custom__">自定义…</option>
                  </select>
                  {isCustom && (
                    <input
                      type="text"
                      autoFocus
                      placeholder="输入模型名"
                      value={settings.openaiModel || ''}
                      onChange={e => updateSetting('openaiModel', e.target.value)}
                    />
                  )}
                </>
              )
            })()}
            <div className="sidebar-hint">
              下拉里是「你的接口实际支持的模型」（自建/代理网关各不相同）。改完 Key 或地址后点「↻ 刷新」重拉；选「自定义…」可手填任意模型名。
              <br />
              <a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer" style={{color:'var(--amber)'}}>
                platform.openai.com/api-keys
              </a>
              {' '}获取官方 Key
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
              data-idx={i}
              className={`tpl-chip${dragChip === i ? ' dragging' : ''}`}
              onMouseDown={e => onChipMouseDown(e, i)}
              title="拖动可调整顺序"
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
            <div className="rp-text">预览：<span>{renamePreview}</span></div>
            <button
              type="button"
              className="token-chip"
              title="刷新画廊中的文件名（按当前字段立即重算）"
              onClick={() => dispatch({ type: Actions.BUMP_RENAME_PREVIEW })}
            >刷新</button>
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
          title="分析整个文件夹；可反复重新分析（已分析的会确认后覆盖）"
        >
          {engineStatus === 'busy' ? '分析中…' : '全局分析'}
        </button>
        <button
          className="btn primary"
          onClick={handleAnalyzeSelected}
          disabled={selectedIds.length === 0 || engineStatus === 'busy'}
          title="分析画廊中点选的照片；可反复重新分析（含已分析的，覆盖结果）"
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

      {/* ── 投稿接口（模式开关，下沉紧贴底部横线）：仅高级摄影师版露出 ── */}
      {proMode && (
        <div className="sidebar-section submit-toggle">
          <button
            className={`btn ${submitMode ? 'primary' : 'ghost'}`}
            onClick={() => dispatch({ type: Actions.SET_SUBMIT_MODE, payload: !submitMode })}
            title="进入/退出投稿模式：在画廊里勾选要投稿的照片后确认提交"
          >
            {submitMode ? '退出投稿模式' : '投稿接口'}
          </button>
        </div>
      )}

      <footer className="sidebar-footer">
        <a
          className="footer-logo-link"
          href="https://www.sdexp.org/"
          target="_blank"
          rel="noreferrer"
          title="星尘远征队 · https://www.sdexp.org/"
        >
          <img className="footer-logo" src="/logo.png" alt="星尘远征队" />
        </a>
        <div className="footer-text">
          <a
            href="https://creativecommons.org/licenses/by-nc-sa/4.0/deed.zh"
            target="_blank"
            rel="noreferrer"
          >
            CC BY-NC-SA 4.0
          </a>
          <a
            className="footer-credit"
            href="https://www.sdexp.org/"
            target="_blank"
            rel="noreferrer"
            title="星尘远征队 · https://www.sdexp.org/"
          >
            星尘远征队 出品
          </a>
        </div>
      </footer>
    </aside>
  )
}
