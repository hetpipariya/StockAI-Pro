import { useLocation, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'

export default function NewsPage() {
  const location = useLocation()
  const navigate = useNavigate()
  
  // Safely fallback to a generic placeholder if accessed directly without state
  const article = location.state?.article || {
    title: "Market News Hub",
    description: "Welcome to the central intelligence hub for stock market updates.",
    source: "System",
    publishedAt: new Date().toISOString()
  }

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-[#0b0f14] text-slate-200">
      <div className="p-4 border-b border-white/5 flex items-center justify-between bg-black/20">
        <button 
          onClick={() => navigate(-1)} 
          className="px-4 py-2 border border-white/10 rounded-lg text-slate-400 font-mono text-sm hover:text-white hover:bg-white/5 transition"
        >
          ← Back to Dashboard
        </button>
        <span className="font-mono font-bold text-teal-400 text-sm">Intelligence News Desk</span>
      </div>

      <main className="flex-1 p-8 overflow-y-auto">
        <motion.div 
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="max-w-3xl mx-auto"
        >
          {article.sentiment && (
            <span className={`inline-block mb-4 px-3 py-1 text-xs font-mono font-bold rounded-lg ${
              article.sentiment === 'positive' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' :
              article.sentiment === 'negative' ? 'bg-red-500/20 text-red-400 border border-red-500/30' :
              'bg-slate-500/20 text-slate-400 border border-slate-500/30'
            }`}>
              {article.sentiment.toUpperCase()} SENTIMENT
            </span>
          )}
          
          <h1 className="text-3xl sm:text-4xl font-bold text-slate-100 mb-4">{article.title}</h1>
          <div className="flex items-center gap-4 text-xs font-mono text-slate-500 mb-8 border-b border-white/5 pb-6">
            <span className="bg-white/5 px-2 py-1 rounded">{article.source}</span>
            <span>{new Date(article.publishedAt).toLocaleString()}</span>
          </div>
          
          {article.image && (
            <img src={article.image} alt={article.title} className="w-full rounded-2xl mb-8 object-cover max-h-96 border border-white/10" />
          )}

          <p className="text-lg text-slate-300 leading-relaxed mb-12">
            {article.description}
          </p>

          {article.url && article.url !== '#' && (
            <a 
              href={article.url} 
              target="_blank" 
              rel="noopener noreferrer" 
              className="px-8 py-3 bg-teal-500/20 text-teal-400 border border-teal-500/40 rounded-xl font-mono font-bold hover:bg-teal-500/30 transition inline-block text-center"
            >
              Read Full Article Source ↗
            </a>
          )}
        </motion.div>
      </main>
    </div>
  )
}
