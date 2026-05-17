import { NavLink } from 'react-router-dom'

const NAV = [
  { to: '/live',     icon: '📡', label: '실시간' },
  { to: '/playback', icon: '🎞️', label: '재생' },
  { to: '/logs',     icon: '📋', label: '로그' },
  { to: '/settings', icon: '⚙️', label: '설정' },
]

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <span className="brand-icon">🎥</span>
        <span className="brand-text">CCTV</span>
      </div>
      <nav className="sidebar-nav">
        {NAV.map(({ to, icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `nav-item ${isActive ? 'active' : ''}`
            }
          >
            <span className="nav-icon">{icon}</span>
            <span className="nav-label">{label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-footer">
        <span className="rec-dot" />
        <span>자동 녹화 중</span>
      </div>
    </aside>
  )
}
