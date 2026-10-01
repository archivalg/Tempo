import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { TempoContextProvider } from './context/TempoContextProvider'
import { ActionDetailPage } from './pages/ActionDetail'
import { ActionsListPage } from './pages/ActionsList'
import AdminPage from './pages/Admin'
import AuditPage from './pages/Audit'
import DataPage from './pages/Data'
import ApprovalsPage from './pages/Approvals'
import AttendancePage from './pages/Attendance'
import DemandPage from './pages/Demand'
import ReportsPage from './pages/Reports'
import AccountPage from './pages/Account'
import InvitePage from './pages/Invite'
import { KioskPage } from './pages/Kiosk'
import { LabourProvidersPage } from './pages/LabourProviders'
import LiveOperationsPage from './pages/LiveOperations'
import { NewActionPage } from './pages/NewAction'
import { NewRunPage } from './pages/NewRun'
import { OnboardingPage } from './pages/Onboarding'
import OverviewPage from './pages/Overview'
import RosterPlannerPage from './pages/RosterPlanner'
import { RunComparisonsPage } from './pages/RunComparisons'
import { RunDetailPage } from './pages/RunDetail'
import { RunsListPage } from './pages/RunsList'

function App() {
  return (
    <TempoContextProvider>
      <BrowserRouter>
        <Routes>
          {/* Kiosk is a device surface: no session, no navigation. */}
          <Route path="/kiosk" element={<KioskPage />} />
          <Route path="/invite" element={<InvitePage />} />
          <Route element={<AppShell />}>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/demand" element={<DemandPage />} />
            <Route path="/roster" element={<RosterPlannerPage />} />
            <Route path="/attendance" element={<AttendancePage />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="/approvals" element={<ApprovalsPage />} />
            <Route path="/live" element={<LiveOperationsPage />} />
            <Route path="/runs" element={<RunsListPage />} />
            <Route path="/runs/new" element={<NewRunPage />} />
            <Route path="/runs/compare" element={<RunComparisonsPage />} />
            <Route path="/runs/:runId" element={<RunDetailPage />} />
            <Route path="/actions" element={<ActionsListPage />} />
            <Route path="/actions/new" element={<NewActionPage />} />
            <Route path="/actions/:actionId" element={<ActionDetailPage />} />
            <Route path="/onboarding" element={<OnboardingPage />} />
            <Route path="/providers" element={<LabourProvidersPage />} />
            <Route path="/admin" element={<AdminPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="/data" element={<DataPage />} />
            <Route path="/account" element={<AccountPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </TempoContextProvider>
  )
}

export default App
