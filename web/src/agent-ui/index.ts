import React, { lazy } from 'react';

// Dynamic registry mapping manifest playground.ui string to lazy component
const UI_REGISTRY: Record<string, React.LazyExoticComponent<React.ComponentType<any>>> = {
  'support-agent': lazy(() => import('./support-agent')),
  'document-analyzer': lazy(() => import('./document-analyzer')),
};

export function getAgentPlaygroundUI(uiName: string) {
  return UI_REGISTRY[uiName] || null;
}
