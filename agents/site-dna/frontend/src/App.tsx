import React, { Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/Layout';
import { Dashboard } from './pages/Dashboard';
import { NewAnalysis } from './pages/NewAnalysis';
import { AnalysisMonitor } from './pages/AnalysisMonitor';
import { History } from './pages/History';
import { Settings } from './pages/Settings';

const ROUTER_BASENAME = (import.meta.env.BASE_URL || '/').replace(/\/+$/, '') || '/';

export default function App() {
  return (
    <BrowserRouter basename={ROUTER_BASENAME}>
      <Suspense
        fallback={
          <div className="min-h-screen flex items-center justify-center text-xs text-[var(--text-3)] font-mono">
            Loading Site DNA...
          </div>
        }
      >
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="analyses/new" element={<NewAnalysis />} />
            <Route path="analyses/:runId" element={<AnalysisMonitor />} />
            <Route path="history" element={<History />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
