import { useEffect, useRef } from 'react'
import { usePhotoStore, usePhotoDispatch, Actions } from './stores/photoStore'
import * as api from './services/api'
import Header from './components/Header'
import Sidebar from './components/Sidebar'
import Gallery from './components/Gallery'
import IndexTable from './components/IndexTable'
import SubmitPanel from './components/SubmitPanel'
import AboutPage from './components/AboutPage'
import AdminPanel from './components/AdminPanel'

export default function App() {
  const { activeTab, error, settings, scanStatus } = usePhotoStore()
  const dispatch = usePhotoDispatch()

  // Track previous folder path to clear search/filters upon folder switch
  const prevFolderPathRef = useRef(settings?.folderPath)
  useEffect(() => {
    if (settings?.folderPath && settings.folderPath !== prevFolderPathRef.current) {
      dispatch({ type: Actions.CLEAR_ALL })
      prevFolderPathRef.current = settings.folderPath
    }
  }, [settings?.folderPath, dispatch])

  // Load settings from backend on mount
  useEffect(() => {
    api.getSettings()
      .then(data => {
        if (data) {
          dispatch({
            type: Actions.SET_SETTINGS,
            payload: {
              engine: data.engine || 'ollama',
              apiKey: data.claude_api_key_masked || '',
              geminiApiKey: data.gemini_api_key_masked || '',
              geminiModel: data.gemini_model || 'gemini-2.5-flash',
              zhipuApiKey: data.zhipu_api_key_masked || '',
              ollamaUrl: data.ollama_url || 'http://localhost:11434',
              ollamaModel: data.ollama_model || 'gemma4:31b',
              prefix: data.rename_prefix || 'SDEXP',
              template: data.rename_template || '[摄影师]_[地点]_[类别]_[日期]',
              folderPath: data.last_folder || '',
            },
          })
        }
      })
      .catch(() => {
        // Backend not yet running, that's fine
      })

    api.getScanProgress()
      .then(progress => {
        if (progress && progress.running) {
          dispatch({ type: Actions.SET_SCAN_STATUS, payload: 'scanning' })
        }
      })
      .catch(() => {
        // Ignored
      })
  }, [dispatch])

  // Authoritatively (re)load the gallery for the active folder whenever the
  // folder changes OR a scan finishes. The `scanStatus` dependency guarantees
  // that, no matter how the scan polling raced, the gallery ends up showing the
  // photos for the current folder once scanning completes.
  useEffect(() => {
    api.getAllPhotos({ folder_path: settings?.folderPath || '' })
      .then(data => {
        if (data && data.photos) {
          dispatch({ type: Actions.SET_PHOTOS, payload: data.photos })
        }
      })
      .catch(() => {
        // Ignored
      })
  }, [settings?.folderPath, scanStatus, dispatch])

  // Clear error after 5s
  useEffect(() => {
    if (error) {
      const t = setTimeout(() => dispatch({ type: Actions.SET_ERROR, payload: null }), 5000)
      return () => clearTimeout(t)
    }
  }, [error, dispatch])

  return (
    <div className="app-layout">
      <Header />
      <div className="app-body">
        {/* 画廊 / 索引表才需要 AI 分析侧栏；投稿管理 / 教程 / 投稿页隐藏，内容铺满 */}
        {['gallery', 'index'].includes(activeTab) && <Sidebar />}
        <main className="app-main">
          {activeTab === 'gallery' && <Gallery />}
          {activeTab === 'index' && <IndexTable />}
          {activeTab === 'submit' && <SubmitPanel />}
          {activeTab === 'about' && <AboutPage />}
          {activeTab === 'admin' && <AdminPanel />}
        </main>
      </div>

      {/* Error toast */}
      {error && (
        <div className="error-toast" onClick={() => dispatch({ type: Actions.SET_ERROR, payload: null })}>
          ⚠️ {error}
        </div>
      )}
    </div>
  )
}
