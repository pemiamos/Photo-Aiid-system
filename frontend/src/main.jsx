import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import { PhotoProvider } from './stores/photoStore.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <PhotoProvider>
      <App />
    </PhotoProvider>
  </React.StrictMode>,
)
