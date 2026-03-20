import { motion } from 'framer-motion'

export default function MarketClosedBanner({ status }) {
    if (!status || status.is_open) return null

    const formatTime = (isoString) => {
        if (!isoString) return ''
        const d = new Date(isoString)
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }

    const formatDay = (isoString) => {
        if (!isoString) return ''
        const d = new Date(isoString)
        return d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })
    }

    return (
        <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center justify-center gap-3 px-4 py-1.5 bg-amber-500/[0.06] border-b border-amber-500/10"
        >
            <span className="relative flex h-2 w-2 shrink-0">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400/60" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-400" />
            </span>
            <span className="text-xs font-mono text-amber-300/80 tracking-wide">
                Market Closed — Showing last trading session data
            </span>
            <span className="text-[10px] font-mono text-amber-500/60">
                Opens {formatDay(status.next_event_time)} {formatTime(status.next_event_time)}
            </span>
        </motion.div>
    )
}
