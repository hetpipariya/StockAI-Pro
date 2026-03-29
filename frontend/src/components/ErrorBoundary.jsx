import React, { Component } from 'react';

export class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    console.error("ErrorBoundary Caught:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          padding: '24px',
          textAlign: 'center',
          background: 'var(--card, #0C1118)',
          borderRadius: '8px',
          border: '1px solid var(--border, #1A2332)',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          fontFamily: 'var(--font-family-base, sans-serif)'
        }}>
          <h3 style={{ color: '#FF4C4C', marginBottom: '8px' }}>Something went wrong.</h3>
          <button 
            onClick={() => window.location.reload()}
            style={{
              padding: '8px 16px',
              background: 'transparent',
              border: '1px solid #FF4C4C',
              color: '#FF4C4C',
              borderRadius: '4px',
              cursor: 'pointer'
            }}>
            Tap to retry
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
