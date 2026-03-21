import { motion, AnimatePresence } from 'framer-motion'
import SentimentPanel from '../SentimentPanel/SentimentPanel'
import { useState, useEffect } from 'react'

export default function IntelligencePanel({ prediction, snapshot, symbol, timeframe, hideNews = false }) {
  const activeData = prediction;

  const toFiniteNumber = (value) => {
    const num = Number(value)
    return Number.isFinite(num) ? num : null
  }

  const formatCurrency = (value, digits = 2, fallback = '₹--') => {
    const num = toFiniteNumber(value)
    return num == null ? fallback : `₹${num.toFixed(digits)}`
  }

  const signal = activeData?.signal || 'HOLD'
  const confidenceRaw = toFiniteNumber(activeData?.confidence)
  const conf = Math.max(0, Math.min(100, confidenceRaw ?? 0))

  const isBuy = signal === 'BUY'
  const isSell = signal === 'SELL'
  const ltp = toFiniteNumber(snapshot?.ltp) ?? 0

  const factors = Array.isArray(activeData?.factors) && activeData.factors.length > 0
    ? activeData.factors.filter((factor) => typeof factor === 'string' && factor.trim().length > 0)
    : [
    "Awaiting AI analysis",
    "Gathering market depth",
    "Processing indicators"
    ]

  const targetValue = toFiniteNumber(activeData?.target)
  const stopValue = toFiniteNumber(activeData?.stop_loss) ?? toFiniteNumber(activeData?.stop)
  const modelEntries = activeData?.models && typeof activeData.models === 'object'
    ? Object.entries(activeData.models)
    : []

  const formatModelValue = (model, value) => {
    const num = toFiniteNumber(value)
    if (num == null) return 'N/A'
    if (model.includes('ratio')) return num.toFixed(2)
    if (model.includes('score') || model.includes('strength')) return num.toFixed(1)
    return formatCurrency(num, 2)
  }

  return (
    <div className="w-full h-full flex flex-col min-h-0 overflow-hidden">
      {/* Scrollable content wrapper */}
      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-hide p-4 space-y-3">

        {/* ─── Signal Engine Card ─── */}
        <motion.div
          className="rounded-2xl border border-white/5 bg-black/60 backdrop-blur-md p-4 shadow-xl overflow-hidden relative"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
        >
          {/* Glow effect for strong signals */}
          {(isBuy || isSell) && (
            <motion.div
              className={`absolute inset-0 rounded-2xl pointer-events-none ${isBuy
                ? 'bg-gradient-to-r from-emerald-500/5 via-transparent to-transparent'
                : 'bg-gradient-to-r from-red-500/5 via-transparent to-transparent'
                }`}
              animate={{ opacity: [0.3, 0.6, 0.3] }}
              transition={{ duration: 2, repeat: Infinity }}
            />
          )}

          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs uppercase tracking-wider text-slate-500 font-mono flex items-center gap-2 relative z-10">
              <span className={`w-2 h-2 rounded-full ${isBuy ? 'bg-emerald-500' : isSell ? 'bg-red-500' : 'bg-amber-500'} animate-pulse`} />
              Signal Engine
            </h3>
            <span className="text-[10px] text-slate-600 font-mono relative z-10">AI Powered</span>
          </div>

          <div className="flex items-center gap-4 mb-4 relative z-10">
            <motion.div
              className={`w-16 h-16 rounded-2xl flex items-center justify-center font-mono font-bold text-lg relative overflow-hidden
                ${isBuy ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40' : isSell ? 'bg-red-500/20 text-red-400 border border-red-500/40' : 'bg-amber-500/20 text-amber-400 border border-amber-500/40'}`}
              animate={isBuy || isSell ? {
                boxShadow: isBuy
                  ? ['0 0 15px rgba(16,185,129,0.2)', '0 0 30px rgba(16,185,129,0.4)', '0 0 15px rgba(16,185,129,0.2)']
                  : ['0 0 15px rgba(239,68,68,0.2)', '0 0 30px rgba(239,68,68,0.4)', '0 0 15px rgba(239,68,68,0.2)']
              } : {}}
              transition={{ duration: 2, repeat: Infinity }}
            >
              {signal}
              {(isBuy || isSell) && (
                <motion.div
                  className={`absolute inset-0 rounded-2xl border-2 ${isBuy ? 'border-emerald-500' : 'border-red-500'}`}
                  animate={{ scale: [1, 1.15], opacity: [0.4, 0] }}
                  transition={{ duration: 1.5, repeat: Infinity }}
                />
              )}
            </motion.div>

            <div className="flex-1">
              <div className="flex justify-between items-center mb-1">
                <p className="text-xs text-slate-500">Confidence</p>
                <motion.p key={conf} initial={{ scale: 1.1 }} animate={{ scale: 1 }} className="text-sm font-mono font-bold text-teal-400">
                  {conf}%
                </motion.p>
              </div>
              <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
                <motion.div
                  className={`h-full rounded-full ${isBuy ? 'bg-emerald-500' : isSell ? 'bg-red-500' : 'bg-amber-500'}`}
                  initial={{ width: 0 }}
                  animate={{ width: `${conf}%` }}
                  transition={{ duration: 0.6, ease: 'easeOut' }}
                />
              </div>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2 text-center relative z-10">
            {[
              { label: 'Regime', value: activeData?.regime || 'Unknown', color: 'slate' },
              { label: 'Target', value: isLoading ? '₹--' : targetValue != null ? formatCurrency(targetValue, 0) : 'Data unavailable', color: 'teal' },
              { label: 'Stop Loss', value: isLoading ? '₹--' : stopValue != null ? formatCurrency(stopValue, 0) : 'Data unavailable', color: 'amber' },
            ].map((metric, i) => (
              <div key={metric.label} className="rounded-lg bg-white/5 py-1.5 flex flex-col justify-center">
                <p className="text-[10px] text-slate-500 mb-0.5">{metric.label}</p>
                <p className={`text-xs font-mono font-bold text-${metric.color}-400 px-1 truncate`} title={metric.value}>
                  {metric.value}
                </p>
              </div>
            ))}
          </div>
        </motion.div>

        {/* ─── Divider ─── */}
        <div className="h-px w-full bg-gradient-to-r from-transparent via-white/10 to-transparent" />

        {/* ─── Key Factors Card ─── */}
        <motion.div
          className="rounded-2xl border border-white/5 bg-black/60 backdrop-blur-md p-4 shadow-xl"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
        >
          <h3 className="text-xs uppercase tracking-wider text-slate-500 font-mono mb-2 flex items-center gap-2">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z" />
            </svg>
            Key Factors
          </h3>
          <div className="space-y-1.5">
            {factors.map((f, i) => (
              <div key={i} className="rounded-lg bg-white/[0.03] p-2.5 flex items-start gap-2">
                <span className="text-teal-500 mt-0.5 text-[10px]">◆</span>
                <p className="text-xs text-slate-300 leading-relaxed">{f}</p>
              </div>
            ))}
          </div>
        </motion.div>

        {/* ─── Divider ─── */}
        <div className="h-px w-full bg-gradient-to-r from-transparent via-white/10 to-transparent" />

        {/* ─── AI Co-pilot Card ─── */}
        <motion.div
          className="rounded-2xl border border-teal-500/15 bg-[#0b0f14]/80 backdrop-blur-md p-4 shadow-xl relative overflow-hidden"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
        >
          <motion.div
            className="absolute inset-0 bg-gradient-to-br from-teal-500/5 via-transparent to-transparent pointer-events-none"
            animate={{ opacity: [0.3, 0.5, 0.3] }}
            transition={{ duration: 3, repeat: Infinity }}
          />

          <h3 className="text-xs uppercase tracking-wider text-teal-400 font-mono mb-2 flex items-center gap-2 relative z-10">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
            </svg>
            AI Co-pilot
          </h3>

          <p className="text-xs text-slate-300 mb-3 leading-relaxed relative z-10">
            {activeData?.explanation || `Model suggests ${symbol} may move higher. Consider entry near support with tight SL.`}
          </p>

          {/* Ensemble Breakdown */}
          {modelEntries.length > 0 && (
            <div className="space-y-1.5 relative z-10">
              <h4 className="text-[10px] uppercase text-slate-500 mb-1">Ensemble Breakdown</h4>
              {modelEntries.map(([model, pVal]) => {
                const modelValue = toFiniteNumber(pVal)
                const toneClass = modelValue == null
                  ? 'text-slate-300'
                  : modelValue > 0
                    ? 'text-emerald-400'
                    : modelValue < 0
                      ? 'text-red-400'
                      : 'text-slate-300'

                return (
                  <div key={model} className="flex justify-between items-center text-xs font-mono bg-black/30 px-3 py-1.5 rounded-lg border border-white/5">
                    <span className="text-slate-400 uppercase">{model}</span>
                    <span className={toneClass}>
                      {formatModelValue(model, modelValue)}
                    </span>
                  </div>
                )
              })}
            </div>
          )}

          {/* Suggested Params */}
          {stopValue != null && targetValue != null && (
            <div className="mt-3 rounded-xl bg-black/40 border border-teal-500/15 p-3 relative z-10">
              <span className="text-[10px] font-mono text-emerald-400 flex items-center gap-1 mb-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                Suggested Params
              </span>
              <div className="flex gap-4">
                <p className="text-[11px] font-mono text-slate-300">
                  SL <span className="text-red-400 font-bold ml-1">{formatCurrency(stopValue, 2)}</span>
                </p>
                <p className="text-[11px] font-mono text-slate-300">
                  TGT <span className="text-emerald-400 font-bold ml-1">{formatCurrency(targetValue, 2)}</span>
                </p>
              </div>
            </div>
          )}
        </motion.div>

        {/* ─── Divider ─── */}
        <div className="h-px w-full bg-gradient-to-r from-transparent via-white/10 to-transparent" />

        {/* ─── Sentiment & News ─── */}
        <div className="space-y-3">
          <SentimentPanel symbol={symbol} />
          {!hideNews && <NewsPanel symbol={symbol} />}
        </div>

      </div>

      {/* Bottom fade shadow to hint at scrollable content */}
      <div className="shrink-0 h-3 bg-gradient-to-t from-[#0b0f14] to-transparent pointer-events-none" />
    </div>
  )
}