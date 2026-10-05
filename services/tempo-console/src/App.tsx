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
import BillingPage from './pages/Billing'
import InvitePage from './pages/Invite'
import { KioskPage } from './pages/Kiosk'
import LandingPage from './pages/Landing'
import Landing2Page from './pages/Landing2'
import { LabourProvidersPage } from './pages/LabourProviders'
import LiveOperationsPage from './pages/LiveOperations'
import { NewActionPage } from './pages/NewAction'
import { NewRunPage } from './pages/NewRun'
import { OnboardingPage } from './pages/Onboarding'
import HelpLibrary from './pages/HelpLibrary'
import OffersPage from './pages/Offers'
import MyTempo from './pages/MyTempo'
import OverviewPage from './pages/Overview'
import RequestsPage from './pages/Requests'
import SetupWizard from './pages/SetupWizard'
import PlatformConsole from './pages/PlatformConsole'
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
          <Route path="/landing" element={<LandingPage />} />
          <Route path="/landing2" element={<Landing2Page />} />
          <Route path="/kiosk" element={<KioskPage />} />
          <Route path="/invite" element={<InvitePage />} />
          {/* Team members: their own roster, offers, leave and clockings on the web. A separate surface from the manager shell. */}
          <Route path="/my/*" element={<MyTempo />} />
          {/* Platform operators have their own surface: a separate shell, banner and navigation, never the customer shell. */}
          <Route path="/platform/*" element={<PlatformConsole />} />
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
            <Route path="/billing" element={<BillingPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="/data" element={<DataPage />} />
            <Route path="/setup" element={<SetupWizard />} />
            <Route path="/offers" element={<OffersPage />} />
            <Route path="/requests" element={<RequestsPage />} />
            <Route path="/help" element={<HelpLibrary />} />
            <Route path="/help/:id" element={<HelpLibrary />} />
            <Route path="/account" element={<AccountPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </TempoContextProvider>
  )
}

export default App
