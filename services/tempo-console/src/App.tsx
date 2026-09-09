import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { TempoContextProvider } from './context/TempoContextProvider'
import { ContextSetupPage } from './pages/ContextSetup'
import { DashboardPage } from './pages/Dashboard'
import { RunsListPage } from './pages/RunsList'
import { NewRunPage } from './pages/NewRun'
import { RunDetailPage } from './pages/RunDetail'
import { ActionsListPage } from './pages/ActionsList'
import { NewActionPage } from './pages/NewAction'
import { ActionDetailPage } from './pages/ActionDetail'
import { OnboardingPage } from './pages/Onboarding'
import { KioskPage } from './pages/Kiosk'
import { TeamAttendancePage } from './pages/TeamAttendance'

function App() {
  return (
    <TempoContextProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/setup" element={<ContextSetupPage />} />
          <Route element={<Layout />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/runs" element={<RunsListPage />} />
            <Route path="/runs/new" element={<NewRunPage />} />
            <Route path="/runs/:runId" element={<RunDetailPage />} />
            <Route path="/actions" element={<ActionsListPage />} />
            <Route path="/actions/new" element={<NewActionPage />} />
            <Route path="/actions/:actionId" element={<ActionDetailPage />} />
            <Route path="/onboarding" element={<OnboardingPage />} />
            <Route path="/kiosk" element={<KioskPage />} />
            <Route path="/attendance" element={<TeamAttendancePage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </TempoContextProvider>
  )
}

export default App
