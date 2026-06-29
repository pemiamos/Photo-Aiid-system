import { usePhotoStore, usePhotoDispatch, Actions } from '../stores/photoStore'
import pkg from '../../package.json'
import './Header.css'

const TABS = [
  { key: 'gallery', label: '画廊' },
  { key: 'index',   label: '索引表' },
  { key: 'about',   label: '使用教程' },
  { key: 'admin',   label: '投稿管理' },
]

const STATUS_TEXT = {
  idle:  '引擎待命',
  busy:  '分析中',
  done:  '分析完成',
  error: '引擎异常',
}

export default function Header() {
  const { activeTab, engineStatus, settings } = usePhotoStore()
  const dispatch = usePhotoDispatch()

  return (
    <header className="header">
      <div className="header-logo">
        <b>Photo-Aiid-system</b>
        <span className="version-badge">v{pkg.version}</span>
      </div>

      <nav className="header-nav">
        {TABS.map(t => (
          <button
            key={t.key}
            className={activeTab === t.key ? 'active' : ''}
            onClick={() => dispatch({ type: Actions.SET_ACTIVE_TAB, payload: t.key })}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <div className="header-right">
        {settings.folderPath && (
          <span className="header-folder">
            <span className="folder-icon">📁</span>
            <span>{settings.folderPath.split('/').pop() || settings.folderPath}</span>
          </span>
        )}
        <span className="engine-indicator">
          <i className={`engine-dot ${engineStatus}`} />
          <span>{STATUS_TEXT[engineStatus] || '引擎待命'}</span>
        </span>
      </div>
    </header>
  )
}
