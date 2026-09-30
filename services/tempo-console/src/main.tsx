import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './design/tempo.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
