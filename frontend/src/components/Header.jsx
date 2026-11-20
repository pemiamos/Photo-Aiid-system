import { usePhotoStore, usePhotoDispatch, Actions } from '../stores/photoStore'
import pkg from '../../package.json'
import './Header.css'

const TABS = [
  { key: 'gallery', label: '画廊' },
  { key: 'index',   label: '索引表' },
  { key: 'about',   label: '使用教程' },
  // 仅高级摄影师版可见
  { key: 'admin',   label: '投稿管理', pro: true },
]

const STATUS_TEXT = {
  idle:  '引擎待命',
  busy:  '分析中',
  done:  '分析完成',
  error: '引擎异常',
}

export default function Header() {
  const { activeTab, engineStatus, settings, proMode } = usePhotoStore()
  const dispatch = usePhotoDispatch()

  const visibleTabs = TABS.filter(t => !t.pro || proMode)

  return (
    <header className="header">
      <div className="header-logo">
        <b>Photo-Aiid-system</b>
        <span className="version-badge">v{pkg.version}</span>
      </div>

      <nav className="header-nav">
        {visibleTabs.map(t => (
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
        {/* 本地视觉预分类：独立页面（后端托管，见 backend/fast_review.html）。
            用 <a> 而不是 tab，因为它是另一套渲染，不共享 React 状态。 */}
        <a
          className="mode-toggle"
          href="/fast"
          target="_blank"
          rel="noreferrer"
          title="本地 CLIP + 人脸检测的预分类：批量粗分类、低置信打标、重复图归组、以图搜图"
          style={{ textDecoration: 'none' }}
        >
          AI 预分类
        </a>
        <button
          className="mode-toggle"
          onClick={() => dispatch({ type: Actions.SET_PRO_MODE, payload: !proMode })}
          title={proMode
            ? '当前为高级摄影师版（含投稿管理 / 云端征稿）。点击切回普通用户版'
            : '当前为普通用户版。点击解锁投稿管理 / 投稿模式 / 云端征稿'}
        >
          {proMode ? '切换到普通用户版' : '切换到高级摄影师版'}
        </button>
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
