import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { datadogRum } from '@datadog/browser-rum'
import './index.css'
import App from './App.jsx'
import EditDog from './EditDog.jsx'

datadogRum.init({
  applicationId: 'd414b7c4-2108-4f2a-9f25-eff381c2bad5',
  clientToken: 'pub18d20e529c36d6611797c708aedfd9b3',
  site: 'datadoghq.com',
  service: 'lahoucine-app-frontend',
  env: 'prod',
  sessionSampleRate: 100,
  sessionReplaySampleRate: 20,
  defaultPrivacyLevel: 'mask-user-input',
  trackUserInteractions: true,
  trackResources: true,
  trackLongTasks: true,
})

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />} />
        <Route path="/edit/:id" element={<EditDog />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
