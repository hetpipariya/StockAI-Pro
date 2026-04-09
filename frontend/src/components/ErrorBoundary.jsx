import React, { Component } from 'react';

export class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    console.error("[ErrorBoundary] Error caught:", error, errorInfo);
    this.setState({
      error,
      errorInfo,
    });
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen w-full bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 flex items-center justify-center p-4">
          <div className="max-w-2xl w-full bg-red-900/20 border border-red-500/30 rounded-lg p-8 backdrop-blur">
            <h2 className="text-red-400 text-2xl font-bold mb-4">Dashboard Error</h2>
            <p className="text-red-300 text-sm mb-6">An error occurred while rendering the dashboard.</p>
            
            <div className="bg-slate-900/50 rounded p-4 mb-6">
              <p className="text-red-200 font-mono text-xs break-all">
                {this.state.error?.toString()}
              </p>
            </div>

            {this.state.errorInfo && (
              <details className="mb-6">
                <summary className="cursor-pointer text-red-300 font-medium mb-2">
                  Stack trace
                </summary>
                <pre className="text-xs text-red-200/60 font-mono mt-2 bg-slate-900/50 p-3 rounded overflow-auto max-h-40">
                  {this.state.errorInfo.componentStack}
                </pre>
              </details>
            )}

            <div className="flex gap-3">
              <button
                onClick={() => window.location.reload()}
                className="flex-1 bg-blue-600 hover:bg-blue-700 text-white py-3 px-4 rounded font-medium transition-colors"
              >
                Reload Page
              </button>
              <button
                onClick={() => window.location.href = '/'}
                className="flex-1 bg-slate-700 hover:bg-slate-600 text-white py-3 px-4 rounded font-medium transition-colors"
              >
                Go Home
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
