import { NavLink, Navigate, Outlet } from 'react-router-dom'
import { useTempoContext } from '../context/TempoContextProvider'

export function Layout() {
  const { context, clearContext } = useTempoContext()

  if (!context) return <Navigate to="/setup" replace />

  return (
    <div className="layout">
      <header className="top-bar">
        <span className="brand">Tempo Console</span>
        <nav>
          <NavLink to="/" end>
            Dashboard
          </NavLink>
          <NavLink to="/runs">Runs</NavLink>
          <NavLink to="/actions">Actions</NavLink>
          <NavLink to="/attendance">Team attendance</NavLink>
          <NavLink to="/kiosk">Kiosk</NavLink>
          <NavLink to="/onboarding">Onboarding</NavLink>
        </nav>
        <div className="identity">
          <span>
            {context.user_id} @ {context.tenant_id} ({context.roles.join(', ') || 'no roles'})
          </span>
          <button onClick={clearContext}>Switch context</button>
        </div>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  )
}
