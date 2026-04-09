/**
 * Landing Page Component
 * Professional, high-converting landing page for StockAI Pro.
 * Hero section, features, and call-to-action.
 */

import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { ArrowRight, Zap, TrendingUp, Brain, Shield, Gauge } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/store/authStore';

/**
 * Animated floating dashboard mockup
 */
function FloatingDashboardMockup() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 40 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.8, delay: 0.2 }}
      className="relative"
    >
      {/* Glow effect */}
      <div className="absolute inset-0 bg-gradient-to-t from-blue-600/30 via-transparent to-transparent rounded-2xl blur-3xl" />

      {/* Dashboard mockup */}
      <motion.div
        animate={{ y: [0, -20, 0] }}
        transition={{ duration: 4, repeat: Infinity, ease: 'easeInOut' }}
        className="relative bg-gradient-to-br from-slate-800 to-slate-900 rounded-2xl border border-blue-500/20 overflow-hidden shadow-2xl"
      >
        <div className="p-6 space-y-4">
          {/* Header */}
          <div className="flex items-center justify-between pb-4 border-b border-blue-500/10">
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 bg-green-400 rounded-full animate-pulse" />
              <span className="text-sm text-slate-300 font-mono">LIVE MARKET DATA</span>
            </div>
            <span className="text-xs text-slate-500">RELIANCE • 1m</span>
          </div>

          {/* Chart area */}
          <div className="h-40 bg-slate-900/50 rounded border border-slate-700/30 flex items-end justify-between px-4 py-3 gap-1">
            {[...Array(12)].map((_, i) => (
              <motion.div
                key={i}
                className={`flex-1 rounded-t ${
                  i % 3 === 0 ? 'bg-green-500/40' : 'bg-red-500/40'
                } border-t border-slate-600/30`}
                initial={{ height: 0 }}
                animate={{ height: `${Math.random() * 100 + 20}%` }}
                transition={{
                  duration: 0.6,
                  delay: i * 0.05,
                  repeat: Infinity,
                  repeatDelay: 2,
                }}
              />
            ))}
          </div>

          {/* Stats */}
          <div className="grid grid-cols-3 gap-3 pt-2 text-xs">
            <div>
              <p className="text-slate-500">₹2,854.50</p>
              <p className="text-green-400 font-semibold">+2.5%</p>
            </div>
            <div>
              <p className="text-slate-500">HIGH: ₹2,875</p>
              <p className="text-slate-400">LOW: ₹2,840</p>
            </div>
            <div className="text-right">
              <p className="text-slate-500">AI Signal</p>
              <p className="text-blue-400 font-semibold">BUY 78%</p>
            </div>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}

/**
 * Feature card component
 */
function FeatureCard({ icon: Icon, title, description, gradientFrom, gradientTo }) {
  return (
    <motion.div
      whileHover={{ y: -8 }}
      className="group relative bg-gradient-to-br from-slate-800/50 to-slate-900/50 border border-blue-500/10 hover:border-blue-500/30 rounded-xl p-6 transition-all"
    >
      {/* Gradient background on hover */}
      <div
        className={`absolute inset-0 opacity-0 group-hover:opacity-10 rounded-xl bg-gradient-to-br ${gradientFrom} ${gradientTo} transition-opacity`}
      />

      <div className="relative z-10">
        <div
          className={`w-12 h-12 rounded-lg mb-4 flex items-center justify-center bg-gradient-to-br ${gradientFrom} ${gradientTo}`}
        >
          <Icon size={24} className="text-white" />
        </div>
        <h3 className="text-lg font-semibold text-white mb-2">{title}</h3>
        <p className="text-sm text-slate-400">{description}</p>
      </div>
    </motion.div>
  );
}

/**
 * Landing Page Component
 * @component
 */
export function LandingPage() {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuthStore();
  const [scrollY, setScrollY] = useState(0);

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/dashboard', { replace: true });
    }
  }, [isAuthenticated, navigate]);

  useEffect(() => {
    const handleScroll = () => setScrollY(window.scrollY);
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950 overflow-hidden">
      {/* Navigation */}
      <nav className="fixed top-0 left-0 right-0 z-50 border-b border-blue-500/10 backdrop-blur-md bg-slate-950/80">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-gradient-to-br from-blue-400 to-cyan-400 rounded-lg flex items-center justify-center">
              <Zap size={20} className="text-slate-950" />
            </div>
            <span className="text-lg font-bold text-white">
              Stock<span className="text-blue-400">AI</span> Pro
            </span>
          </div>

          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            onClick={() => navigate('/login')}
            className="px-6 py-2 rounded-lg bg-gradient-to-r from-blue-500 to-cyan-500 text-white font-semibold hover:shadow-lg hover:shadow-blue-500/50 transition-all"
          >
            Enter Terminal
          </motion.button>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="pt-32 pb-20 px-6 relative overflow-hidden">
        {/* Animated background orbs */}
        <motion.div
          animate={{ x: scrollY * 0.5 }}
          className="absolute top-0 left-1/2 -translate-x-1/2 w-96 h-96 bg-blue-600/10 rounded-full blur-3xl opacity-40"
        />

        <div className="max-w-6xl mx-auto grid lg:grid-cols-2 gap-12 items-center relative z-10">
          {/* Left content */}
          <motion.div
            initial={{ opacity: 0, x: -40 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.8 }}
          >
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.1 }}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-blue-500/10 border border-blue-500/20 mb-6"
            >
              <Zap size={16} className="text-blue-400" />
              <span className="text-sm text-blue-300">Premium Trading Terminal</span>
            </motion.div>

            <h1 className="text-5xl lg:text-6xl font-bold text-white mb-6 leading-tight">
              AI-Powered <span className="bg-gradient-to-r from-blue-400 to-cyan-400 bg-clip-text text-transparent">Market Intelligence</span> for Indian Traders
            </h1>

            <p className="text-lg text-slate-400 mb-8 leading-relaxed">
              Experience next-generation trading with real-time AI signals, advanced charting, and lightning-fast execution. Designed for professional traders who demand excellence.
            </p>

            <div className="flex flex-col sm:flex-row gap-4">
              <motion.button
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                onClick={() => navigate('/login')}
                className="px-8 py-4 rounded-lg bg-gradient-to-r from-blue-500 to-cyan-500 text-white font-semibold flex items-center justify-center gap-2 hover:shadow-lg hover:shadow-blue-500/50 transition-all"
              >
                Access Terminal
                <ArrowRight size={20} />
              </motion.button>

              <motion.button
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                className="px-8 py-4 rounded-lg border border-blue-500/30 bg-slate-900/50 text-white font-semibold hover:bg-slate-800/50 transition-colors"
              >
                View Demo
              </motion.button>
            </div>

            {/* Trust indicators */}
            <div className="mt-12 flex items-center gap-6 text-sm text-slate-400">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 bg-green-400 rounded-full" />
                <span>Sub-100ms Latency</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 bg-green-400 rounded-full" />
                <span>NSE/BSE Integrated</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 bg-green-400 rounded-full" />
                <span>Admin Verified</span>
              </div>
            </div>
          </motion.div>

          {/* Right: Dashboard mockup */}
          <FloatingDashboardMockup />
        </div>
      </section>

      {/* Features Section */}
      <section className="py-20 px-6 relative">
        <div className="max-w-6xl mx-auto">
          <motion.div
            initial={{ opacity: 0 }}
            whileInView={{ opacity: 1 }}
            transition={{ duration: 0.6 }}
            viewport={{ once: true }}
            className="text-center mb-16"
          >
            <h2 className="text-4xl font-bold text-white mb-4">
              Enterprise-Grade Features
            </h2>
            <p className="text-lg text-slate-400 max-w-2xl mx-auto">
              Built for professional traders who demand the best tools in the market.
            </p>
          </motion.div>

          <motion.div
            initial={{ opacity: 0 }}
            whileInView={{ opacity: 1 }}
            transition={{ duration: 0.6 }}
            viewport={{ once: true }}
            className="grid md:grid-cols-2 lg:grid-cols-3 gap-6"
          >
            <FeatureCard
              icon={TrendingUp}
              title="AI-Powered Signals"
              description="Real-time trading signals powered by advanced ML models analyzing 50+ indicators."
              gradientFrom="from-green-500"
              gradientTo="to-emerald-500"
            />

            <FeatureCard
              icon={Gauge}
              title="Lightning-Fast Execution"
              description="Sub-100ms order execution with zero latency. Execute faster than the competition."
              gradientFrom="from-blue-500"
              gradientTo="to-cyan-500"
            />

            <FeatureCard  
              icon={Brain}
              title="Smart Risk Management"
              description="Automatic position sizing, stop-loss calculations, and portfolio optimization."
              gradientFrom="from-purple-500"
              gradientTo="to-violet-500"
            />

            <FeatureCard
              icon={Gauge}
              title="Multi-Timeframe Analysis"
              description="Analyze trends across 1m, 5m, 15m, 1h, and daily timeframes simultaneously."
              gradientFrom="from-orange-500"
              gradientTo="to-red-500"
            />

            <FeatureCard
              icon={Shield}
              title="Enterprise Security"
              description="Bank-level encryption, secure authentication, and comprehensive audit logs."
              gradientFrom="from-indigo-500"
              gradientTo="to-blue-500"
            />

            <FeatureCard
              icon={Zap}
              title="Real-Time Data"
              description="Instant market data updates, tick-by-tick quotes, and live L1/L2 data."
              gradientFrom="from-yellow-500"
              gradientTo="to-amber-500"
            />
          </motion.div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-20 px-6">
        <motion.div
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          transition={{ duration: 0.6 }}
          viewport={{ once: true }}
          className="max-w-4xl mx-auto bg-gradient-to-r from-blue-600/20 to-cyan-600/20 border border-blue-500/20 rounded-2xl p-12 text-center"
        >
          <h2 className="text-3xl font-bold text-white mb-4">
            Ready to Transform Your Trading?
          </h2>
          <p className="text-lg text-slate-300 mb-8">
            Join the elite traders using StockAI Pro for data-driven, AI-powered decisions.
          </p>
          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            onClick={() => navigate('/login')}
            className="px-8 py-4 rounded-lg bg-gradient-to-r from-blue-500 to-cyan-500 text-white font-semibold inline-flex items-center gap-2 hover:shadow-lg hover:shadow-blue-500/50 transition-all"
          >
            Enter the Terminal
            <ArrowRight size={20} />
          </motion.button>
        </motion.div>
      </section>

      {/* Footer */}
      <footer className="border-t border-blue-500/10 bg-slate-950/50 py-8 px-6">
        <div className="max-w-6xl mx-auto text-center text-sm text-slate-500">
          <p>© 2026 StockAI Pro. Premium Trading Terminal. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
}

export default LandingPage;
