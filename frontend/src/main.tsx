import React from 'react'
import ReactDOM from 'react-dom/client'
import { createHashRouter, Navigate, RouterProvider } from 'react-router-dom'

import App from './App'
import AnalyzerPage from './pages/AnalyzerPage'
import ReportPage from './pages/ReportPage'
import ReportsPage from './pages/ReportsPage'
import TreePage from './pages/TreePage'
import UpdaterPage from './pages/UpdaterPage'
import UsersPage from './pages/UsersPage'
import './styles.css'

const router = createHashRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <Navigate to="/reports" replace /> },
      { path: 'reports', element: <ReportsPage /> },
      { path: 'reports/:kind/:quarter', element: <ReportPage /> },
      { path: 'reports/:kind/:quarter/tree', element: <TreePage /> },
      { path: 'reports/:kind/:quarter/analyze', element: <AnalyzerPage /> },
      { path: 'reports/:kind/:quarter/update-file', element: <UpdaterPage /> },
      { path: 'admin/users', element: <UsersPage /> },
    ],
  },
])

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
)
