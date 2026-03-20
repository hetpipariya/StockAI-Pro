import { useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

/**
 * Mobile Bottom Sheet — replaces the old right-side MobileDrawer.
 * Features: drag handle, swipe-down to dismiss, overlay click to close.
 */
export default function MobileDrawer({ open, onClose, title, children }) {
  const sheetRef = useRef(null)
  const startY = useRef(0)
  const currentY = useRef(0)

  const handleTouchStart = useCallback((e) => {
    startY.current = e.touches[0].clientY
  }, [])

  const handleTouchMove = useCallback((e) => {
    currentY.current = e.touches[0].clientY
    const delta = currentY.current - startY.current
    if (delta > 0 && sheetRef.current) {
      sheetRef.current.style.transform = `translateY(${delta}px)`
    }
  }, [])

  const handleTouchEnd = useCallback(() => {
    const delta = currentY.current - startY.current
    if (delta > 100) {
      onClose()
    }
    if (sheetRef.current) {
      sheetRef.current.style.transform = ''
    }
    startY.current = 0
    currentY.current = 0
  }, [onClose])

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40"
          />
          {/* Bottom Sheet */}
          <motion.div
            ref={sheetRef}
            initial={{ y: '100%' }}
            animate={{ y: 0 }}
            exit={{ y: '100%' }}
            transition={{ type: 'spring', damping: 28, stiffness: 280 }}
            className="mobile-bottom-sheet z-50"
            style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
            onTouchStart={handleTouchStart}
            onTouchMove={handleTouchMove}
            onTouchEnd={handleTouchEnd}
          >
            {/* Drag handle */}
            <div className="drag-handle" />

            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-white/5 shrink-0">
              <h3 className="text-sm font-mono font-semibold text-slate-200">{title}</h3>
              <button
                onClick={onClose}
                className="p-2 rounded-lg text-slate-500 hover:text-slate-200 hover:bg-white/5 touch-target"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto overscroll-contain" style={{ WebkitOverflowScrolling: 'touch' }}>
              {children}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
