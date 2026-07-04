import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { DocumentModal } from './components/DocumentModal'
import { SearchPage } from './pages/SearchPage'
import { AppProvider, useApp } from './store'

// Код-сплит (D12): тяжёлые экраны и cytoscape грузятся отдельными чанками.
const GraphPage = lazy(() => import('./pages/GraphPage').then((m) => ({ default: m.GraphPage })))
const DashboardPage = lazy(() => import('./pages/DashboardPage').then((m) => ({ default: m.DashboardPage })))
const SubscriptionsPage = lazy(() =>
  import('./pages/SubscriptionsPage').then((m) => ({ default: m.SubscriptionsPage })),
)
const ComparePage = lazy(() => import('./pages/ComparePage').then((m) => ({ default: m.ComparePage })))

function PageFallback() {
  return (
    <div className="flex h-full items-center justify-center text-fg-muted">
      <div className="flex items-center gap-3">
        <span className="h-4 w-4 rounded-full border-2 border-accent border-t-transparent animate-spin" />
        Загрузка экрана…
      </div>
    </div>
  )
}

function Shell() {
  const { role, setRole } = useApp()
  return (
    <Layout role={role} onRoleChange={setRole}>
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route path="/" element={<SearchPage />} />
          <Route path="/graph" element={<GraphPage />} />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/subscriptions" element={<SubscriptionsPage />} />
          <Route path="*" element={<SearchPage />} />
        </Routes>
      </Suspense>
      <DocumentModal />
    </Layout>
  )
}

export default function App() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  )
}
