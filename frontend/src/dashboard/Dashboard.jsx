/**
 * Premium Trading Dashboard
 * Main dashboard component with search, charts, watchlist, and signals.
 * Desktop and mobile responsive with glassmorphism design.
 */

import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { LogOut, Settings, Bell, Loader } from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import { useMarketStore } from '@/store/marketStore'
import { useNavigate } from 'react-router-dom'
import AdvancedSearch from '@/components/search/AdvancedSearch'
import TradingViewChart from '@/components/charts/TradingViewChart'
import { marketAPI, predictAPI } from '@/services/api/client'

export function Dashboard() {
  const navigate = useNavigate()
  const { logout } = useAuthStore()
  const { selectedSymbol, setSelectedSymbol } = useMarketStore()
  const [showNotifications, setShowNotifications] = useState(false)
  const [renderError, setRenderError] = useState(null)
  const [notifications] = useState([
    { id: 1, type: 'signal', message: 'Market data connected and updating' },
    { id: 2, type: 'execution', message: 'Real-time market data enabled' },
  ])

  // Debug logging
  React.useEffect(() => {
    console.log('[Dashboard] Component mounted with selectedSymbol:', selectedSymbol)
  }, [selectedSymbol])

  // Fetch symbols
  const { data: symbols = [], isLoading: symbolsLoading } = useQuery({
    queryKey: ['symbols'],
    queryFn: async () => {
      try {
        console.log('[Dashboard] Fetching symbols...')
        const response = await marketAPI.getSymbols(100)
        console.log('[Dashboard] Symbols fetched:', response.data)
        const symbolsList = Array.isArray(response.data.data) ? response.data.data : []
        // Extract symbol strings from objects, or use as-is if already strings
        const symbolStrings = symbolsList.map(item => 
          typeof item === 'string' ? item : item.symbol
        ).filter(Boolean)
        return symbolStrings
      } catch (error) {
        console.error('[Dashboard] Symbols fetch error:', error.message, error.response?.data)
        setRenderError(`Failed to load symbols: ${error.message}`)
        return []
      }
    },
    staleTime: 60 * 1000,
    retry: 2,
  })

  React.useEffect(() => {
    console.log('[Dashboard] Symbols updated:', symbols, 'Loading:', symbolsLoading)
  }, [symbols, symbolsLoading])

  // Fetch snapshot
  const { data: snapshot, isLoading: snapshotLoading } = useQuery({
    queryKey: ['snapshot', selectedSymbol],
    queryFn: async () => {
      if (!selectedSymbol) return null
      try {
        console.log('[Dashboard] Fetching snapshot for:', selectedSymbol)
        const response = await marketAPI.getSnapshot(selectedSymbol)
        console.log('[Dashboard] Snapshot fetched:', response.data)
        return response.data?.data
      } catch (error) {
        console.error('[Dashboard] Snapshot fetch error:', error.message, error.response?.data)
        return null
      }
    },
    enabled: !!selectedSymbol,
    refetchInterval: 10 * 1000,
    retry: 2,
  })

  // Fetch candles
  const { data: candlesData = {}, isLoading: candlesLoading } = useQuery({
    queryKey: ['candles', selectedSymbol, '1m'],
    queryFn: async () => {
      if (!selectedSymbol) return { candles: [] }
      try {
        console.log('[Dashboard] Fetching candles for:', selectedSymbol)
        const response = await marketAPI.getCandles(selectedSymbol, '1m', 100)
        console.log('[Dashboard] Candles fetched:', response.data)
        return response.data.data || { candles: [] }
      } catch (error) {
        console.error('[Dashboard] Candles fetch error:', error.message, error.response?.data)
        return { candles: [] }
      }
    },
    enabled: !!selectedSymbol,
    refetchInterval: 30 * 1000,
    retry: 2,
  })

  // Fetch AI signal
  const { data: signal } = useQuery({
    queryKey: ['signal', selectedSymbol],
    queryFn: async () => {
      if (!selectedSymbol) return null
      try {
        console.log('[Dashboard] Fetching signal for:', selectedSymbol)
        const response = await predictAPI.getSignal(selectedSymbol)
        console.log('[Dashboard] Signal fetched:', response.data)
        return response.data.data
      } catch (error) {
        console.error('[Dashboard] Signal fetch error:', error.message, error.response?.data)
        return null
      }
    },
    enabled: !!selectedSymbol,
    staleTime: 60 * 1000,
    retry: 1,
  })

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="min-h-screen w-full bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950">
      {/* Error Display Panel */}
      {renderError && (
        <div className="fixed top-4 right-4 z-[9999] max-w-md bg-red-900/80 border border-red-500/50 rounded-lg p-4 backdrop-blur">
          <div className="flex gap-3">
            <div className="flex-1">
              <p className="text-red-200 font-medium">Error Loading Dashboard</p>
              <p className="text-red-300 text-sm mt-1">{renderError}</p>
            </div>
            <button
              onClick={() => setRenderError(null)}
              className="text-red-300 hover:text-red-100 text-lg leading-none"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Debug Info Panel (Development) */}
      {process.env.NODE_ENV === 'development' && (
        <div className="fixed bottom-4 left-4 z-[9999] max-w-xs bg-slate-800/80 border border-blue-500/30 rounded-lg p-3 text-xs backdrop-blur">
          <div className="space-y-1 text-slate-300">
            <p>Selected: {selectedSymbol || 'None'}</p>
            <p>Symbols: {symbols.length} loaded</p>
            <p>Loading Symbols: {symbolsLoading ? 'Yes' : 'No'}</p>
            <p>Snapshot: {snapshot ? 'Loaded' : 'Not loaded'}</p>
            <p>Candles: {candlesData?.candles?.length || 0}</p>
          </div>
        </div>
      )}
      {/* Header */}
      <header className="fixed top-0 left-0 right-0 z-50 border-b border-blue-500/10 backdrop-blur-md bg-slate-950/80">
        <div className="max-w-full px-6 py-4 flex items-center justify-between gap-6">
          <div className="flex items-center gap-2 flex-shrink-0">
            <div className="w-8 h-8 bg-gradient-to-br from-blue-400 to-cyan-400 rounded-lg" />
            <span className="font-bold text-white hidden sm:block">StockAI Pro</span>
          </div>

          <div className="flex-1 max-w-md">
            <AdvancedSearch />
          </div>

          <div className="flex items-center gap-4">
            <div className="relative">
              <motion.button
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                onClick={() => setShowNotifications(!showNotifications)}
                className="relative p-2 rounded-lg hover:bg-slate-800/50 transition-colors"
              >
                <Bell size={20} className="text-slate-400 hover:text-blue-400" />
                {notifications.length > 0 && (
                  <span className="absolute top-1 right-1 w-2 h-2 bg-red-500 rounded-full animate-pulse" />
                )}
              </motion.button>

              {showNotifications && (
                <motion.div
                  initial={{ opacity: 0, y: -10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="absolute top-12 right-0 w-80 bg-slate-800/95 border border-blue-500/20 rounded-lg shadow-xl z-50"
                >
                  <div className="p-4 border-b border-blue-500/10">
                    <h3 className="font-semibold text-white text-sm">Notifications</h3>
                  </div>
                  <div className="max-h-64 overflow-y-auto">
                    {notifications.map((notif) => (
                      <div
                        key={notif.id}
                        className="px-4 py-3 border-b border-slate-700/30 hover:bg-slate-700/30 transition-colors text-sm"
                      >
                        <p className="text-slate-200">{notif.message}</p>
                      </div>
                    ))}
                  </div>
                </motion.div>
              )}
            </div>

            <motion.button
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              className="p-2 rounded-lg hover:bg-slate-800/50 transition-colors"
            >
              <Settings size={20} className="text-slate-400 hover:text-blue-400" />
            </motion.button>

            <motion.button
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              onClick={handleLogout}
              className="px-4 py-2 rounded-lg bg-slate-800/50 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors text-sm font-medium flex items-center gap-2"
            >
              <LogOut size={16} />
              <span className="hidden sm:inline">Logout</span>
            </motion.button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="pt-24 px-6 pb-6">
        <div className="max-w-full">
          <div className="grid lg:grid-cols-[300px_1fr_320px] gap-6">
            {/* Left Sidebar - Symbols */}
            <motion.div
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.1 }}
              className="hidden lg:block h-[calc(100vh-180px)] overflow-hidden"
            >
              <div className="bg-gradient-to-b from-slate-800/40 to-slate-900/40 border border-blue-500/10 rounded-xl p-6 h-full overflow-y-auto backdrop-blur">
                <h3 className="text-sm font-semibold text-white mb-4 uppercase tracking-wider">
                  Available Symbols
                </h3>
                <div className="space-y-2">
                  {symbols.map((symbol) => (
                    <motion.button
                      key={symbol}
                      onClick={() => setSelectedSymbol(symbol)}
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      className={`w-full text-left px-4 py-3 rounded-lg transition-all ${
                        selectedSymbol === symbol
                          ? 'bg-gradient-to-r from-blue-500 to-cyan-500 text-white font-semibold'
                          : 'bg-slate-700/30 hover:bg-slate-600/30 text-slate-200'
                      }`}
                    >
                      {symbol}
                    </motion.button>
                  ))}
                  {symbols.length === 0 && (
                    <p className="text-slate-400 text-sm text-center py-8">Loading symbols...</p>
                  )}
                </div>
              </div>
            </motion.div>

            {/* Center - Chart */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
              className="h-[calc(100vh-180px)]"
            >
              {candlesLoading && selectedSymbol ? (
                <div className="h-full flex items-center justify-center bg-slate-800/40 rounded-xl border border-blue-500/10">
                  <Loader size={32} className="text-blue-400 animate-spin" />
                </div>
              ) : (
                <TradingViewChart
                  candles={candlesData.candles || []}
                  symbol={selectedSymbol}
                  interval="1m"
                />
              )}
            </motion.div>

            {/* Right Sidebar - Stats & Signals */}
            <motion.div
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.3 }}
              className="hidden lg:block h-[calc(100vh-180px)] overflow-y-auto space-y-6"
            >
              {/* Stock Details */}
              <div className="bg-gradient-to-b from-slate-800/40 to-slate-900/40 border border-blue-500/10 rounded-xl p-6 backdrop-blur">
                <h3 className="text-sm font-semibold text-white mb-4 uppercase tracking-wider">
                  {selectedSymbol || 'No Symbol Selected'}
                </h3>

                {snapshotLoading && selectedSymbol ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader size={20} className="text-blue-400 animate-spin" />
                  </div>
                ) : snapshot ? (
                  <div className="space-y-4">
                    <div>
                      <p className="text-xs text-slate-400 mb-1">Last Price</p>
                      <p className="text-2xl font-bold text-white">
                        ₹{snapshot.price?.toLocaleString('en-IN', {
                          maximumFractionDigits: 2,
                        })}
                      </p>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <p className="text-xs text-slate-400 mb-1">CHANGE</p>
                        <p
                          className={`font-semibold ${
                            snapshot.change >= 0
                              ? 'text-green-400'
                              : 'text-red-400'
                          }`}
                        >
                          {snapshot.change >= 0 ? '+' : ''}
                          {snapshot.change?.toFixed(2)}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-400 mb-1">%</p>
                        <p
                          className={`font-semibold ${
                            snapshot.changePercent >= 0
                              ? 'text-green-400'
                              : 'text-red-400'
                          }`}
                        >
                          {snapshot.changePercent >= 0 ? '+' : ''}
                          {snapshot.changePercent?.toFixed(2)}%
                        </p>
                      </div>
                    </div>

                    <div className="pt-4 border-t border-slate-700/30 space-y-3 text-xs">
                      <div className="flex justify-between">
                        <span className="text-slate-400">HIGH</span>
                        <span className="text-white font-medium">
                          ₹{snapshot.high?.toLocaleString('en-IN', {
                            maximumFractionDigits: 2,
                          })}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-slate-400">LOW</span>
                        <span className="text-white font-medium">
                          ₹{snapshot.low?.toLocaleString('en-IN', {
                            maximumFractionDigits: 2,
                          })}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-slate-400">VOLUME</span>
                        <span className="text-white font-medium">
                          {(snapshot.volume / 1000000)?.toFixed(1)}M
                        </span>
                      </div>
                      {snapshot.pe_ratio && (
                        <div className="flex justify-between">
                          <span className="text-slate-400">P/E Ratio</span>
                          <span className="text-white font-medium">{snapshot.pe_ratio?.toFixed(2)}</span>
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <p className="text-slate-400 text-sm text-center py-8">Select a symbol to view details</p>
                )}
              </div>

              {/* AI Signal Card */}
              <div className="bg-gradient-to-br from-blue-500/20 to-cyan-500/10 border border-blue-500/20 rounded-xl p-6 backdrop-blur">
                <h3 className="text-sm font-semibold text-white mb-4 uppercase tracking-wider">
                  AI Signal
                </h3>
                <div className="text-center">
                  {signal ? (
                    <>
                      <div
                        className={`text-5xl font-bold mb-2 ${
                          signal.signal === 'BUY' ? 'text-green-400' : 'text-red-400'
                        }`}
                      >
                        {signal.signal}
                      </div>
                      <div className="text-3xl font-bold text-white mb-4">
                        {(signal.confidence * 100).toFixed(0)}%
                      </div>
                      <p className="text-sm text-slate-300 mb-4">Confidence Level</p>
                      <motion.button
                        whileHover={{ scale: 1.02 }}
                        whileTap={{ scale: 0.98 }}
                        className="w-full py-2 rounded-lg bg-gradient-to-r from-blue-500 to-cyan-500 text-white font-semibold hover:shadow-lg hover:shadow-blue-500/50 transition-all"
                      >
                        View Details
                      </motion.button>
                    </>
                  ) : (
                    <p className="text-slate-400 text-sm py-8">Select a symbol to view signal</p>
                  )}
                </div>
              </div>
            </motion.div>
          </div>
        </div>
      </main>
    </div>
  )
}

export default Dashboard
