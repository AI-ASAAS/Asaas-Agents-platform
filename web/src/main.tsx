import './asaas-ui/styles/index.css';
import './styles/catalog.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Ambient, ToastProvider } from './asaas-ui';
import { LangProvider } from './content';
import App from './App';

// Clear chunk-reload flag after clean startup
try {
  sessionStorage.removeItem('chunk-reload');
} catch {
  // Storage unavailable, continue
}

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('Failed to find root element');
}

createRoot(rootElement).render(
  <StrictMode>
    <ToastProvider>
      <LangProvider>
        <Ambient />
        <App />
      </LangProvider>
    </ToastProvider>
  </StrictMode>,
);
