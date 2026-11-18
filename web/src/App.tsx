import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Layout } from './components/Layout';
import { ErrorBoundary } from './components/ErrorBoundary';
import { Skeleton } from './asaas-ui';

const Home = lazy(() => import('./pages/Home'));
const About = lazy(() => import('./pages/About'));
const Privacy = lazy(() => import('./pages/Privacy'));
const Terms = lazy(() => import('./pages/Terms'));
const AgentDetail = lazy(() => import('./pages/AgentDetail'));
const NotFound = lazy(() => import('./pages/NotFound'));

export function App() {
  return (
    <BrowserRouter>
      <ErrorBoundary>
        <Suspense
          fallback={
            <div className="container" style={{ paddingBlock: 'var(--gutter, 20px)' }}>
              <Skeleton count={3} height={120} />
            </div>
          }
        >
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<Home />} />
              <Route path="about" element={<About />} />
              <Route path="privacy" element={<Privacy />} />
              <Route path="terms" element={<Terms />} />
              <Route path="agents/:slug" element={<AgentDetail />} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </Suspense>
      </ErrorBoundary>
    </BrowserRouter>
  );
}

export default App;
