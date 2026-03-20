import { useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

export default function SignalToast({ signal, symbol, confidence, target, onClose }) {
    useEffect(() => {
        const timer = setTimeout(() => {
            onClose()
        }, 5000)
        return () => clearTimeout(timer)
    }, [onClose])

    const isBuy = signal === 'BUY'

    return (
        <motion.div
            initial={{ opacity: 0, y: 50, scale: 0.9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.9 }}
            className={`fixed bottom-6 right-6 z-50 rounded-2xl border p-4 shadow-2xl backdrop-blur-md flex items-start gap-4 w-80
        ${isBuy
                    ? 'bg-emerald-950/80 border-emerald-500/30 shadow-[0_10px_40px_rgba(16,185,129,0.2)]'
                    : 'bg-red-950/80 border-red-500/30 shadow-[0_10px_40px_rgba(239,68,68,0.2)]'
                }`}
        >
            <div className={`p-2 rounded-xl mt-1
        ${isBuy ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}
      `}>
                <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    {isBuy ? (
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
                    ) : (
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 17h8m0 0V9m0 8l-8-8-4 4-6-6" />
                    )}
                </svg>
            </div>

            <div className="flex-1">
                <div className="flex justify-between items-center mb-1">
                    <span className="font-mono font-bold text-white tracking-wider flex items-center gap-1">
                        {symbol} <span className={isBuy ? 'text-emerald-400' : 'text-red-400'}>{signal}</span>
                    </span>
                    <span className="text-xs font-mono text-slate-400">{confidence}% Conf</span>
                </div>
                <p className="text-xs text-slate-300 font-mono">
                    AI strongly suggests a {signal} trade.
                    {target && <span> TGT: ₹{target.toFixed(2)}</span>}
                </p>
            </div>

            <button onClick={onClose} className="text-slate-500 hover:text-white transition-colors">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
            </button>

            {/* Progress bar */}
            <motion.div
                className={`absolute bottom-0 left-0 h-1 rounded-b-2xl ${isBuy ? 'bg-emerald-500' : 'bg-red-500'}`}
                initial={{ width: "100%" }}
                animate={{ width: "0%" }}
                transition={{ duration: 5, ease: "linear" }}
            />
        </motion.div>
    )
}
