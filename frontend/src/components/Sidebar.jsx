import { useState, useCallback } from 'react'
import { usePhotoStore, usePhotoDispatch, Actions } from '../stores/photoStore'
import * as api from '../services/api'
import './Sidebar.css'

const ENGINES = [
  { value: 'claude', label: 'Claude API' },
  { value: 'ollama', label: 'Ollama 本地' },
  { value: 'clip',   label: 'CLIP 本地' },
]

export default function Sidebar() {
  const state = usePhotoStore()
  const dispatch = usePhotoDispatch()
  const { photos, tags, settings, engineStatus, stats, activeTag } = state

  const [testResult, setTestResult] = useState(null)
  const [scanning, setScanning] = useState(false)

  /* ── settings update helper ── */
  const updateSetting = useCallback((key, value) => {
    dispatch({ type: Actions.SET_SETTINGS, payload: { [key]: value } })
  }, [dispatch])

  /* ── scan folder ── */
  const handleScan = useCallback(async () => {
    if (!settings.folderPath.trim()) return
    setScanning(true)
    dispatch({ type: Actions.SET_SCAN_STATUS, payload: 'scanning' })
    try {
      const data = await api.scanFolder(settings.folderPath.trim())
      if (data && data.photos) {
        dispatch({ type: Actions.SET_PHOTOS, payload: data.photos })
        dispatch({ type: Actions.SET_SCAN_STATUS, payload: 'done' })
      }
    } catch (err) {
      dispatch({ type: Actions.SET_ERROR, payload: err.message })
      dispatch({ type: Actions.SET_SCAN_STATUS, payload: 'idle' })
    } finally {
      setScanning(false)
    }
  }, [settings.folderPath, dispatch])

  /* ── analyze ── */
  const handleAnalyze = useCallback(async () => {
    dispatch({ type: Actions.SET_ENGINE_STATUS, payload: 'busy' })
    dispatch({ type: Actions.SET_ANALYSIS_PROGRESS, payload: { current: 0, total: photos.length } })
    try {
      const data = await api.analyzePhotos({
        engine: settings.engine,
        api_key: settings.apiKey,
        ollama_url: settings.ollamaUrl,
        ollama_model: settings.ollamaModel,
      })
      if (data && data.photos) {
        dispatch({ type: Actions.SET_PHOTOS, payload: data.photos })
      }
      dispatch({ type: Actions.SET_ENGINE_STATUS, payload: 'done' })
    } catch (err) {
      dispatch({ type: Actions.SET_ERROR, payload: err.message })
      dispatch({ type: Actions.SET_ENGINE_STATUS, payload: 'error' })
    } finally {
      dispatch({ type: Actions.SET_ANALYSIS_PROGRESS, payload: null })
    }
  }, [photos.length, settings, dispatch])

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

  /* ── collect all tags from photos ── */
  const allTags = []
  const tagSet = new Set()
  photos.forEach(p => {
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

  const analyzedCount = photos.filter(p => p.status === 'done' || p.ai_tags).length
  const renamedCount = photos.filter(p => p.renamed).length

  return (
    <aside className="sidebar">
      {/* ── 链接照片 ── */}
      <div className="sidebar-section">
        <h3>链接照片</h3>
        <div className="folder-input-row">
          <input
            type="text"
            placeholder="文件夹路径，如 /Users/photos"
            value={settings.folderPath}
            onChange={e => updateSetting('folderPath', e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleScan()}
          />
          <button
            className="btn primary"
            onClick={handleScan}
            disabled={scanning || !settings.folderPath.trim()}
          >
            {scanning ? '扫描中…' : '扫描'}
          </button>
        </div>
        <div className="sidebar-hint">
          非侵入 · 不复制不上传，仅建立索引
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
        <div className="stat-row"><span>照片</span><b>{photos.length}</b></div>
        <div className="stat-row"><span>已分析</span><b>{analyzedCount}</b></div>
        <div className="stat-row"><span>标签数</span><b>{allTags.length}</b></div>
        <div className="stat-row"><span>已重命名</span><b>{renamedCount}</b></div>
      </div>

      {/* ── actions ── */}
      <div className="sidebar-section">
        <button
          className="btn primary"
          onClick={handleAnalyze}
          disabled={photos.length === 0 || engineStatus === 'busy'}
        >
          {engineStatus === 'busy' ? '分析中…' : '开始 AI 分析'}
        </button>
        <button
          className="btn ghost"
          onClick={handleClear}
          disabled={photos.length === 0}
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
