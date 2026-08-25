import { NavLink, Outlet, useParams } from 'react-router-dom'

export default function App() {
  const { kind, quarter } = useParams()

  return (
    <div className="app">
      <header className="topbar">
        <h1>Backlog Report Platform</h1>
        <nav>
          <NavLink to="/reports" end>
            Reports
          </NavLink>
          {kind && quarter && (
            <>
              <NavLink to={`/reports/${kind}/${quarter}`} end>
                Table
              </NavLink>
              <NavLink to={`/reports/${kind}/${quarter}/tree`}>Tree</NavLink>
              <NavLink to={`/reports/${kind}/${quarter}/analyze`}>Analyzer</NavLink>
              <NavLink to={`/reports/${kind}/${quarter}/update-file`}>Updater</NavLink>
            </>
          )}
          <NavLink to="/admin/users">Users</NavLink>
        </nav>
      </header>
      <Outlet />
    </div>
  )
}
