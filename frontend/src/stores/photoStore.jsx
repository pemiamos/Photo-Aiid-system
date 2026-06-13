import { createContext, useContext, useReducer, useCallback } from 'react'

/* ── initial state ── */
const initialState = {
  photos: [],
  tags: [],
  settings: {
    engine: 'claude',
    apiKey: '',
    ollamaUrl: 'http://localhost:11434',
    ollamaModel: 'gemma4:31b',
    prefix: 'SDEXP',
    template: '[前缀]_[AI标签]_[日期]_[序号]',
    folderPath: '',
  },
  engineStatus: 'idle',       // idle | busy | done | error
  scanStatus: 'idle',         // idle | scanning | done
  analysisProgress: null,     // { current, total } | null
  activeTab: 'gallery',       // gallery | index | about
  activeTag: null,
  searchQuery: '',
  searchResults: null,        // null = no semantic search active
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
  SET_ACTIVE_TAG: 'SET_ACTIVE_TAG',
  SET_SEARCH_QUERY: 'SET_SEARCH_QUERY',
  SET_SEARCH_RESULTS: 'SET_SEARCH_RESULTS',
  SET_STATS: 'SET_STATS',
  SET_ERROR: 'SET_ERROR',
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

    case Actions.SET_ACTIVE_TAG:
      return { ...state, activeTag: action.payload }

    case Actions.SET_SEARCH_QUERY:
      return { ...state, searchQuery: action.payload }

    case Actions.SET_SEARCH_RESULTS:
      return { ...state, searchResults: action.payload }

    case Actions.SET_STATS:
      return { ...state, stats: { ...state.stats, ...action.payload } }

    case Actions.SET_ERROR:
      return { ...state, error: action.payload }

    case Actions.CLEAR_ALL:
      return {
        ...initialState,
        settings: state.settings,   // preserve settings on clear
        activeTab: state.activeTab,
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
