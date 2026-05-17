import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import LivePage from './pages/LivePage'
import PlaybackPage from './pages/PlaybackPage'
import LogPage from './pages/LogPage'
import SettingsPage from './pages/SettingsPage'
import './index.css'

export default function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        <Sidebar />
        <main className="app-content">
          <Routes>
            <Route path="/" element={<Navigate to="/live" replace />} />
            <Route path="/live" element={<LivePage />} />
            <Route path="/playback" element={<PlaybackPage />} />
            <Route path="/logs" element={<LogPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
