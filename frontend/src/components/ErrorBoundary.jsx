import React from 'react'

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  componentDidCatch(error, info) {
    console.error('UI ErrorBoundary caught an error:', error, info)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="w-full h-full min-h-[120px] rounded-xl border border-red-500/20 bg-red-500/5 p-4 flex items-center justify-center">
          <p className="text-xs sm:text-sm text-red-300 font-mono text-center">
            Component unavailable. Market data continues in other panels.
          </p>
        </div>
      )
    }

    return this.props.children
  }
}
