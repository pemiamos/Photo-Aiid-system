import { useEffect } from 'react'
import { usePhotoStore, usePhotoDispatch, Actions } from './stores/photoStore'
import * as api from './services/api'
import Header from './components/Header'
import Sidebar from './components/Sidebar'
import Gallery from './components/Gallery'
import IndexTable from './components/IndexTable'
import AboutPage from './components/AboutPage'

export default function App() {
  const { activeTab, error } = usePhotoStore()
  const dispatch = usePhotoDispatch()

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
  }, [dispatch])

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
