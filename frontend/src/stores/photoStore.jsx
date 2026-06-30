import { createContext, useContext, useReducer, useCallback } from 'react'

/* 用户模式：普通用户版（默认，隐藏投稿/征稿）⇄ 高级摄影师版（完整功能）。
   存 localStorage，重启恢复上次状态。 */
const PRO_MODE_KEY = 'ui_pro_mode'
function loadProMode() {
  try { return localStorage.getItem(PRO_MODE_KEY) === '1' } catch { return false }
}
function saveProMode(on) {
  try { localStorage.setItem(PRO_MODE_KEY, on ? '1' : '0') } catch { /* 忽略 */ }
}

/* ── initial state ── */
const initialState = {
  photos: [],
  tags: [],
  settings: {
    engine: 'ollama',
    apiKey: '',
    geminiApiKey: '',
    geminiModel: 'gemini-2.5-flash',
    zhipuApiKey: '',
    openaiApiKey: '',
    openaiModel: 'gpt-4o-mini',
    openaiBaseUrl: 'https://api.openai.com/v1',
    ollamaUrl: 'http://localhost:11434',
    ollamaModel: 'gemma4:31b',
    prefix: 'SDEXP',
    template: '[摄影师]_[地点]_[类别]_[日期]',
    folderPath: '',
  },
  engineStatus: 'idle',       // idle | busy | done | error
  scanStatus: 'idle',         // idle | scanning | done
  analysisProgress: null,     // { current, total } | null
  activeTab: 'gallery',       // gallery | index | submit | about | admin
  proMode: loadProMode(),     // 高级摄影师版（露出投稿/征稿）；false=普通用户版
  submitMode: false,          // 投稿模式：锁定编辑、画廊选片投稿
  activeTag: null,
  selectedIds: [],            // user-selected photo ids for 自选分析
  searchQuery: '',
  searchResults: null,        // null = no semantic search active
  renamePreviewNonce: 0,      // bump 一下让画廊重算「拟重命名」预览（侧栏刷新按钮用）
  stats: {
    total: 0,
    analyzed: 0,
    tags: 0,
    renamed: 0,
  },
  error: null,
}

/* ── action types ── */
export const Actions = {
  SET_PHOTOS: 'SET_PHOTOS',
  ADD_PHOTOS: 'ADD_PHOTOS',
  UPDATE_PHOTO: 'UPDATE_PHOTO',
  REMOVE_PHOTO: 'REMOVE_PHOTO',
  SET_TAGS: 'SET_TAGS',
  SET_SETTINGS: 'SET_SETTINGS',
  SET_ENGINE_STATUS: 'SET_ENGINE_STATUS',
  SET_SCAN_STATUS: 'SET_SCAN_STATUS',
  SET_ANALYSIS_PROGRESS: 'SET_ANALYSIS_PROGRESS',
  SET_ACTIVE_TAB: 'SET_ACTIVE_TAB',
  SET_PRO_MODE: 'SET_PRO_MODE',
  SET_SUBMIT_MODE: 'SET_SUBMIT_MODE',
  SET_ACTIVE_TAG: 'SET_ACTIVE_TAG',
  TOGGLE_SELECT: 'TOGGLE_SELECT',
  SET_SELECTED: 'SET_SELECTED',
  CLEAR_SELECTION: 'CLEAR_SELECTION',
  SET_SEARCH_QUERY: 'SET_SEARCH_QUERY',
  SET_SEARCH_RESULTS: 'SET_SEARCH_RESULTS',
  SET_STATS: 'SET_STATS',
  SET_ERROR: 'SET_ERROR',
  BUMP_RENAME_PREVIEW: 'BUMP_RENAME_PREVIEW',
  CLEAR_ALL: 'CLEAR_ALL',
}

/* ── reducer ── */
function photoReducer(state, action) {
  switch (action.type) {
    case Actions.SET_PHOTOS:
      return { ...state, photos: action.payload }

    case Actions.ADD_PHOTOS:
      return { ...state, photos: [...state.photos, ...action.payload] }

    case Actions.UPDATE_PHOTO:
      return {
        ...state,
        photos: state.photos.map(p =>
          p.id === action.payload.id ? { ...p, ...action.payload } : p
        ),
      }

    case Actions.REMOVE_PHOTO:
      return {
        ...state,
        photos: state.photos.filter(p => p.id !== action.payload),
      }

    case Actions.SET_TAGS:
      return { ...state, tags: action.payload }

    case Actions.SET_SETTINGS:
      return { ...state, settings: { ...state.settings, ...action.payload } }

    case Actions.SET_ENGINE_STATUS:
      return { ...state, engineStatus: action.payload }

    case Actions.SET_SCAN_STATUS:
      return { ...state, scanStatus: action.payload }

    case Actions.SET_ANALYSIS_PROGRESS:
      return { ...state, analysisProgress: action.payload }

    case Actions.SET_ACTIVE_TAB:
      return { ...state, activeTab: action.payload }

    case Actions.SET_PRO_MODE: {
      const on = !!action.payload
      saveProMode(on)
      // 切回普通版时：退出投稿模式；若正停在投稿/投稿管理页则回画廊，避免停在已隐藏的页面
      const leaving = !on && (state.activeTab === 'admin' || state.activeTab === 'submit')
      return {
        ...state,
        proMode: on,
        submitMode: on ? state.submitMode : false,
        activeTab: leaving ? 'gallery' : state.activeTab,
      }
    }

    case Actions.SET_SUBMIT_MODE:
      // 退出投稿模式时，若停留在投稿页则回到画廊
      return {
        ...state,
        submitMode: action.payload,
        activeTab: action.payload
          ? state.activeTab
          : (state.activeTab === 'submit' ? 'gallery' : state.activeTab),
      }

    case Actions.SET_ACTIVE_TAG:
      return { ...state, activeTag: action.payload }

    case Actions.TOGGLE_SELECT: {
      const id = action.payload
      const exists = state.selectedIds.includes(id)
      return {
        ...state,
        selectedIds: exists
          ? state.selectedIds.filter(x => x !== id)
          : [...state.selectedIds, id],
      }
    }

    case Actions.SET_SELECTED:
      return { ...state, selectedIds: action.payload || [] }

    case Actions.CLEAR_SELECTION:
      return { ...state, selectedIds: [] }

    case Actions.SET_SEARCH_QUERY:
      return { ...state, searchQuery: action.payload }

    case Actions.SET_SEARCH_RESULTS:
      return { ...state, searchResults: action.payload }

    case Actions.SET_STATS:
      return { ...state, stats: { ...state.stats, ...action.payload } }

    case Actions.SET_ERROR:
      return { ...state, error: action.payload }

    case Actions.BUMP_RENAME_PREVIEW:
      return { ...state, renamePreviewNonce: state.renamePreviewNonce + 1 }

    case Actions.CLEAR_ALL:
      return {
        ...initialState,
        settings: state.settings,           // preserve settings on clear
        activeTab: state.activeTab,
        // Preserve in-flight job status so switching folders (which dispatches
        // CLEAR_ALL) does not interrupt the scan/analysis polling that loads
        // photos into the gallery.
        scanStatus: state.scanStatus,
        engineStatus: state.engineStatus,
        analysisProgress: state.analysisProgress,
      }

    default:
      return state
  }
}

/* ── context ── */
const PhotoContext = createContext(null)
const DispatchContext = createContext(null)

export function PhotoProvider({ children }) {
  const [state, dispatch] = useReducer(photoReducer, initialState)

  return (
    <PhotoContext.Provider value={state}>
      <DispatchContext.Provider value={dispatch}>
        {children}
      </DispatchContext.Provider>
    </PhotoContext.Provider>
  )
}

export function usePhotoStore() {
  const state = useContext(PhotoContext)
  if (state === null) throw new Error('usePhotoStore must be used inside PhotoProvider')
  return state
}

export function usePhotoDispatch() {
  const dispatch = useContext(DispatchContext)
  if (dispatch === null) throw new Error('usePhotoDispatch must be used inside PhotoProvider')
  return dispatch
}
