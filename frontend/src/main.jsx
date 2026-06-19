import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { datadogRum } from '@datadog/browser-rum'
import './index.css'
import App from './App.jsx'
import EditDog from './EditDog.jsx'
import Login from './Login.jsx'

datadogRum.init({
  applicationId: 'e0f7fa29-2446-43ce-8630-b4fe5a967f56',
  clientToken: 'pubddf1a207ece4bc29863bc12ee28651ea',
  site: 'datadoghq.com',
  service: 'lahoucine-app-frontend',
  env: 'prod',
  sessionSampleRate: 100,
  sessionReplaySampleRate: 100,
  defaultPrivacyLevel: 'mask-user-input',
  trackUserInteractions: true,
  trackResources: true,
  trackLongTasks: true,
  // RUM ↔ APM correlation: inject distributed tracing headers into API calls
  allowedTracingUrls: [
    {
      match: (url) => url.startsWith(window.location.origin + '/api/'),
      propagatorTypes: ['datadog', 'tracecontext'],
    },
  ],
  traceSampleRate: 100,
})

datadogRum.setGlobalContextProperty('team', 'pre-sales-engineering')

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />} />
        <Route path="/edit/:id" element={<EditDog />} />
        <Route path="/login" element={<Login />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
