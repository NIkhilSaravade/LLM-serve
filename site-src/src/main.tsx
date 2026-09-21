import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/bricolage-grotesque/index.css'
import '@fontsource-variable/fraunces/index.css'
import '@fontsource-variable/instrument-sans/index.css'
import '@fontsource-variable/jetbrains-mono/index.css'
import './styles.css'
import App from './App'

const root = document.getElementById('root')
if (!root) throw new Error('#root missing from index.html')
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
