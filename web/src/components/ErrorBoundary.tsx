import { Component, type ReactNode } from 'react';
import { ErrorState } from '../asaas-ui';
import { t } from '../content';

interface Props {
  children: ReactNode;
}

interface State {
  error: unknown;
}

export class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: unknown): State {
    return { error };
  }

  override componentDidCatch(error: unknown) {
    // After a deploy, old chunk names return 404. Reload once to fetch the new build.
    const chunkFailed =
      error instanceof Error &&
      /dynamically imported module|Loading chunk/i.test(error.message);
    if (chunkFailed && !sessionStorage.getItem('chunk-reload')) {
      sessionStorage.setItem('chunk-reload', '1');
      location.reload();
    }
  }

  override render() {
    if (!this.state.error) {
      return this.props.children;
    }

    return (
      <div className="container" style={{ paddingBlock: 'var(--gutter, 20px)' }}>
        <ErrorState
          error={new Error(t('error.page'))}
          onRetry={() => location.reload()}
        />
      </div>
    );
  }
}
