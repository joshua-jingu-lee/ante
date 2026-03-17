import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ErrorBoundary from './components/common/ErrorBoundary'
import ToastContainer from './components/common/Toast'
import ProtectedRoute from './components/auth/ProtectedRoute'
import Layout from './components/layout/Layout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Approvals from './pages/Approvals'
import ApprovalDetail from './pages/ApprovalDetail'
import Treasury from './pages/Treasury'
import TreasuryHistory from './pages/TreasuryHistory'
import Strategies from './pages/Strategies'
import StrategyDetail from './pages/StrategyDetail'
import Bots from './pages/Bots'
import BotDetail from './pages/BotDetail'
import BacktestData from './pages/BacktestData'
import Agents from './pages/Agents'
import AgentDetail from './pages/AgentDetail'
import Settings from './pages/Settings'
import NotFound from './pages/NotFound'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
})

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ToastContainer />
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route
              element={
                <ProtectedRoute>
                  <Layout />
                </ProtectedRoute>
              }
            >
              <Route index element={<Dashboard />} />
              <Route path="approvals" element={<Approvals />} />
              <Route path="approvals/:id" element={<ApprovalDetail />} />
              <Route path="treasury" element={<Treasury />} />
              <Route path="treasury/history" element={<TreasuryHistory />} />
              <Route path="strategies" element={<Strategies />} />
              <Route path="strategies/:id" element={<StrategyDetail />} />
              <Route path="bots" element={<Bots />} />
              <Route path="bots/:id" element={<BotDetail />} />
              <Route path="backtest-data" element={<BacktestData />} />
              <Route path="members" element={<Agents />} />
              <Route path="members/:id" element={<AgentDetail />} />
              <Route path="settings" element={<Settings />} />
              <Route path="*" element={<NotFound />} />
            </Route>
            <Route path="*" element={<NotFound />} />
          </Routes>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}
