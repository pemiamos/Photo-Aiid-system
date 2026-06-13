import { useEffect, useRef } from 'react'
import { usePhotoStore, usePhotoDispatch, Actions } from './stores/photoStore'
import * as api from './services/api'
import Header from './components/Header'
import Sidebar from './components/Sidebar'
import Gallery from './components/Gallery'
import IndexTable from './components/IndexTable'
import AboutPage from './components/AboutPage'

export default function App() {
  const { activeTab, error, settings } = usePhotoStore()
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
              engine: data.engine || 'claude',
              apiKey: data.claude_api_key || '',
              geminiApiKey: data.gemini_api_key || '',
              geminiModel: data.gemini_model || 'gemini-2.5-flash',
              ollamaUrl: data.ollama_url || 'http://localhost:11434',
              ollamaModel: data.ollama_model || 'gemma3:12b',
              prefix: data.rename_prefix || 'SDEXP',
              template: data.rename_template || '[前缀]_[AI标签]_[日期]_[序号]',
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

  // Fetch photos whenever the active folder path changes
  useEffect(() => {
    api.getPhotos({ folder_path: settings?.folderPath || '' })
      .then(data => {
        if (data && data.photos) {
          dispatch({ type: Actions.SET_PHOTOS, payload: data.photos })
        }
      })
      .catch(() => {
        // Ignored
      })
  }, [settings?.folderPath, dispatch])

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
        <Sidebar />
        <main className="app-main">
          {activeTab === 'gallery' && <Gallery />}
          {activeTab === 'index' && <IndexTable />}
          {activeTab === 'about' && <AboutPage />}
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
