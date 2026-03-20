import { useState, useRef } from 'react'
import { motion } from 'framer-motion'

export default function AiVoiceButton({ prediction, snapshot, symbol }) {
  const [playing, setPlaying] = useState(false)
  const synthRef = useRef(null)

  const speak = () => {
    if (typeof window === 'undefined' || !window.speechSynthesis) return

    if (playing) {
      window.speechSynthesis.cancel()
      setPlaying(false)
      return
    }

    const text = prediction
      ? `${symbol}. Prediction: ${prediction.signal}. Confidence ${prediction.confidence} percent. ${prediction.explanation || 'Model suggests potential upward move.'}`
      : `${symbol}. LTP ₹${Number(snapshot?.ltp || 2500).toFixed(0)}. No prediction available.`

    const utterance = new SpeechSynthesisUtterance(text)
    utterance.rate = 0.9
    utterance.lang = 'en-IN'
    utterance.onend = () => setPlaying(false)
    utterance.onerror = () => setPlaying(false)
    window.speechSynthesis.speak(utterance)
    synthRef.current = utterance
    setPlaying(true)
  }

  return (
    <motion.button
      onClick={speak}
      whileHover={{ scale: 1.05 }}
      whileTap={{ scale: 0.95 }}
      className={`p-3 rounded-xl border backdrop-blur-md transition-all
        ${playing ? 'bg-teal-500/20 border-teal-500/50 text-teal-400 shadow-[0_0_20px_rgba(20,184,166,0.3)]' : 'bg-white/5 border-white/10 text-slate-400 hover:text-teal-400 hover:border-teal-500/30'}`}
      title="AI Voice Insight"
    >
      <motion.svg
        className="w-5 h-5"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        animate={playing ? { scale: [1, 1.1, 1] } : {}}
        transition={{ repeat: playing ? Infinity : 0, duration: 1 }}
      >
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
      </motion.svg>
    </motion.button>
  )
}
