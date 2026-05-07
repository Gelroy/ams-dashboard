import { NavLink } from 'react-router-dom'

interface NavSection {
  label: string
  items: { to: string; label: string }[]
}

const sections: NavSection[] = [
  {
    label: 'Work',
    items: [
      { to: '/critical', label: 'Critical' },
      { to: '/activities', label: 'Activities' },
    ],
  },
  {
    label: 'Data',
    items: [
      { to: '/customers', label: 'Customers' },
      { to: '/versions', label: 'Versions' },
      { to: '/baskets', label: 'Baskets' },
    ],
  },
  {
    label: 'Operations',
    items: [{ to: '/patch-execution', label: 'Patch Execution' }],
  },
  {
    label: 'Config',
    items: [
      { to: '/analytics', label: 'Analytics' },
      { to: '/staff', label: 'Staff' },
      { to: '/settings', label: 'Settings' },
    ],
  },
]

export function SidebarNav() {
  return (
    <nav className="sidenav">
      <div className="nav-brand">AMS Dashboard</div>
      {sections.map((s) => (
        <div key={s.label}>
          <div className="nav-section-label">{s.label}</div>
          {s.items.map((it) => (
            <NavLink
              key={it.to}
              to={it.to}
              className={({ isActive }) => (isActive ? 'nav-item active' : 'nav-item')}
            >
              {it.label}
            </NavLink>
          ))}
        </div>
      ))}
    </nav>
  )
}
