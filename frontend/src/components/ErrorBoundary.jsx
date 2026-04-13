import React from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    this.setState({ error, errorInfo });
    console.error('Error caught:', error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex items-center justify-center min-h-screen bg-[#060810] text-white">
          <div className="max-w-md text-center">
            <AlertCircle className="w-16 h-16 mx-auto mb-4 text-red-500" />
            <h1 className="text-2xl font-bold mb-2">Something went wrong</h1>
            <p className="text-gray-400 mb-4">
              {this.state.error?.message || 'An unexpected error occurred'}
            </p>
            <div className="space-y-2">
              <button
                onClick={this.handleReset}
                className="w-full px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-semibold flex items-center justify-center gap-2 transition"
              >
                <RefreshCw className="w-4 h-4" /> Try Again
              </button>
              <button
                onClick={() => (window.location.href = '/')}
                className="w-full px-4 py-2 bg-gray-800 hover:bg-gray-700 text-white rounded-lg font-semibold transition"
              >
                Go to Home
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