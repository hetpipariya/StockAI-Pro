import React from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { ChevronRight, Activity, TrendingUp, ShieldAlert, Zap, BarChart2, Star, CheckCircle, Globe } from 'lucide-react';

const Landing = () => {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-stockai-bg text-white overflow-x-hidden relative selection:bg-stockai-neon selection:text-black font-sans">
      {/* Animated 3D Grid pattern */}
      <div 
        className="fixed inset-0 bg-grid-pattern opacity-[0.15] pointer-events-none z-0"
        style={{ 
          backgroundSize: '80px 80px', 
          transform: 'perspective(1000px) rotateX(60deg) translateY(-20px) scale(3)',
          transformOrigin: 'top center',
          animation: 'float 20s linear infinite'
        }}
        aria-hidden="true"
      />

      {/* Floating Ambient Orbs */}
      <div className="fixed top-1/4 left-1/4 w-[500px] h-[500px] bg-stockai-neon/10 rounded-full blur-[140px] mix-blend-screen pointer-events-none z-0" />
      <div className="fixed bottom-1/4 right-1/4 w-[600px] h-[600px] bg-blue-500/10 rounded-full blur-[150px] mix-blend-screen animate-pulse-slow pointer-events-none z-0" />

      {/* Navigation */}
      <nav className="relative z-50 flex items-center justify-between px-8 py-6 max-w-7xl mx-auto backdrop-blur-md border-b border-white/5 rounded-b-3xl">
        <div className="flex items-center gap-2 text-2xl font-bold tracking-tighter">
          <Activity className="w-8 h-8 text-stockai-neon" />
          StockAI<span className="text-stockai-neon drop-shadow-[0_0_10px_rgba(0,255,159,0.8)]">Pro</span>
        </div>
        <div className="hidden md:flex gap-8 text-sm font-medium text-stockai-muted">
          <a href="#features" className="hover:text-white transition-colors">Features</a>
          <a href="#demo" className="hover:text-white transition-colors">Platform</a>
          <a href="#pricing" className="hover:text-white transition-colors">Pricing</a>
        </div>
        <button 
          onClick={() => navigate('/login')}
          className="px-6 py-2.5 rounded-full border border-stockai-neon/50 text-stockai-neon hover:bg-stockai-neon hover:text-black hover:shadow-[0_0_20px_rgba(0,255,159,0.4)] transition-all duration-300 font-semibold text-sm"
        >
          Traders Login
        </button>
      </nav>

      {/* Hero Section */}
      <section className="relative z-10 flex flex-col items-center justify-center pt-32 pb-24 text-center px-4 max-w-5xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, ease: "easeOut" }}
          className="inline-flex items-center gap-3 px-4 py-2 rounded-full bg-stockai-surface border border-white/10 mb-8 backdrop-blur-sm shadow-[0_4px_24px_rgba(0,0,0,0.4)]"
        >
          <span className="relative flex h-3 w-3">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-stockai-neon opacity-75"></span>
            <span className="relative inline-flex rounded-full h-3 w-3 bg-stockai-neon"></span>
          </span>
          <span className="text-sm font-medium text-gray-300 tracking-wide uppercase">Live NSE/BSE Signal Engine Active</span>
        </motion.div>

        <motion.h1 
          className="text-5xl md:text-8xl font-extrabold tracking-tighter mb-6 leading-[1.1]"
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.8, delay: 0.1 }}
        >
          AI Trading That <br/>
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-stockai-neon via-emerald-400 to-cyan-400 drop-shadow-[0_0_30px_rgba(0,255,159,0.3)]">
            Thinks Faster Than You.
          </span>
        </motion.h1>

        <motion.p 
          className="text-lg md:text-2xl text-stockai-muted mb-12 max-w-3xl leading-relaxed"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8, delay: 0.2 }}
        >
          Outsmart the Indian market with institutional-grade AI signals, multi-timeframe analysis, and lightning-fast execution. No fluff, just pure alpha.
        </motion.p>

        <motion.div 
          className="flex flex-col sm:flex-row gap-6 w-full sm:w-auto perspective-1000"
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.4 }}
        >
          <button 
            onClick={() => navigate('/login')}
            className="group flex items-center justify-center gap-2 px-10 py-5 rounded-full bg-stockai-neon text-black font-extrabold text-lg hover:shadow-[0_0_40px_rgba(0,255,159,0.6)] hover:scale-105 transition-all duration-300 w-full sm:w-auto"
          >
            Terminal Access 
            <ChevronRight className="w-6 h-6 group-hover:translate-x-1 transition-transform" />
          </button>
          <button className="flex items-center justify-center gap-2 px-10 py-5 rounded-full bg-stockai-surface text-white font-semibold text-lg hover:bg-white/10 border border-white/10 backdrop-blur-md transition-all duration-300 w-full sm:w-auto">
            View Live Demo
          </button>
        </motion.div>
      </section>

      {/* Live Ticker Marquee */}
      <section className="relative z-10 w-full border-y border-white/5 bg-black/40 backdrop-blur-xl overflow-hidden py-4">
        <div className="flex whitespace-nowrap animate-[marquee_20s_linear_infinite]" style={{ animation: "marquee 20s linear infinite" }}>
          {[...Array(3)].map((_, i) => (
            <div key={i} className="flex gap-12 px-6 items-center flex-shrink-0">
              <span className="flex items-center gap-2 font-mono text-lg"><span className="text-white font-bold">RELIANCE</span> <span className="text-stockai-neon">+1.2%</span></span>
              <span className="text-white/20">•</span>
              <span className="flex items-center gap-2 font-mono text-lg"><span className="text-white font-bold">HDFCBANK</span> <span className="text-stockai-sell">-0.4%</span></span>
              <span className="text-white/20">•</span>
              <span className="flex items-center gap-2 font-mono text-lg"><span className="text-white font-bold">TCS</span> <span className="text-stockai-neon">+0.8%</span></span>
              <span className="text-white/20">•</span>
              <span className="flex items-center gap-2 font-mono text-lg"><span className="text-white font-bold">INFY</span> <span className="text-stockai-neon">+2.1%</span></span>
              <span className="text-white/20">•</span>
              <span className="flex items-center gap-2 font-mono text-lg"><span className="text-white font-bold">ITC</span> <span className="text-stockai-sell">-0.1%</span></span>
              <span className="text-white/20">•</span>
            </div>
          ))}
        </div>
      </section>

      {/* Dashboard Preview Section */}
      <section id="demo" className="relative z-10 py-24 px-4 max-w-7xl mx-auto">
        <div className="text-center mb-16">
          <h2 className="text-3xl md:text-5xl font-bold tracking-tight mb-4">Command Center Perfected</h2>
          <p className="text-stockai-muted text-lg max-w-2xl mx-auto">Built purely for execution. See multi-timeframe charts and AI sentiment in a single glance.</p>
        </div>
        
        <motion.div 
          initial={{ opacity: 0, y: 50, rotateX: 10 }}
          whileInView={{ opacity: 1, y: 0, rotateX: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 1, type: "spring" }}
          className="relative rounded-[2rem] border border-white/10 bg-stockai-card/40 p-2 md:p-3 shadow-[0_0_100px_rgba(0,0,0,0.8)] backdrop-blur-2xl ring-1 ring-white/5"
          style={{ transformPerspective: 1200 }}
        >
          <div className="absolute inset-0 bg-gradient-to-t from-stockai-bg via-transparent to-transparent z-20 rounded-[2.5rem] pointer-events-none md:h-full"></div>
          <div className="w-full h-[400px] md:h-[600px] bg-[#0A0E14] rounded-3xl border border-white/5 overflow-hidden flex flex-col relative">
            {/* Fake Dashboard Header */}
            <div className="h-12 border-b border-white/5 flex items-center px-4 gap-2 bg-gradient-to-r from-black to-transparent">
              <div className="flex gap-1.5 object-contain">
                <div className="w-3 h-3 rounded-full bg-stockai-sell" />
                <div className="w-3 h-3 rounded-full bg-yellow-500" />
                <div className="w-3 h-3 rounded-full bg-stockai-neon" />
              </div>
              <div className="mx-auto bg-white/5 px-8 md:px-32 py-1 rounded-md text-xs text-stockai-muted font-mono tracking-widest hidden md:block">STOCKAI // HFT TERMINAL</div>
            </div>
            {/* Fake Dashboard Body */}
            <div className="flex-1 flex p-2 md:p-4 gap-4">
              <div className="w-64 bg-white/5 rounded-xl border border-white/5 hidden md:flex flex-col p-4 gap-3">
                <div className="h-8 bg-white/10 rounded w-full" />
                <div className="h-12 bg-white/10 rounded w-full mt-4" />
                <div className="h-12 bg-white/5 rounded w-full" />
                <div className="h-12 bg-white/5 rounded w-full" />
              </div>
              <div className="flex-1 bg-grid-pattern opacity-60 rounded-xl border border-white/5 relative items-center justify-center flex flex-col gap-4">
                 <BarChart2 className="w-16 h-16 text-stockai-neon/30" />
                 <div className="w-full absolute bottom-0 h-1/2 bg-gradient-to-t from-stockai-neon/10 to-transparent" />
              </div>
              <div className="w-80 bg-gradient-to-br from-white/10 to-transparent rounded-xl border border-stockai-neon/20 hidden lg:flex flex-col p-4 shadow-[0_0_30px_rgba(0,255,159,0.05)]">
                 <div className="text-stockai-neon font-bold text-xs tracking-widest mb-4 flex items-center gap-2"><Zap className="w-3 h-3" /> AI SENTIMENT</div>
                 <div className="text-4xl font-extrabold text-white mb-2">LONG</div>
                 <div className="text-stockai-muted text-sm mb-4">Probability: 89%</div>
                 <div className="h-2 bg-white/10 rounded-full overflow-hidden w-full mb-6">
                    <div className="h-full bg-stockai-neon w-[85%]" />
                 </div>
                 <div className="flex-1 bg-white/5 rounded-xl border border-white/5" />
              </div>
            </div>
          </div>
        </motion.div>
      </section>

      {/* Feature Grid */}
      <section id="features" className="relative z-10 py-24 bg-black/50 border-y border-white/5 backdrop-blur-xl">
        <div className="max-w-7xl mx-auto px-4">
          <div className="text-center mb-16">
            <h2 className="text-3xl md:text-5xl font-bold tracking-tight mb-4">Unfair Advantage Setup</h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8 w-full">
            {[
              { icon: <Zap className="text-cyan-400 w-8 h-8 mb-6"/>, title: "Real-time Processing", desc: "100ms market data latency. Our backend practically syncs directly with live ticks." },
              { icon: <TrendingUp className="text-stockai-neon w-8 h-8 mb-6"/>, title: "Predictive AI Engine", desc: "Random Forest models predicting market setups across 50+ Nifty technical indicators." },
              { icon: <ShieldAlert className="text-stockai-sell w-8 h-8 mb-6"/>, title: "Dynamic Risk Context", desc: "Every signal arrives with calculated stop-losses, target levels, and real-time liquidity scoring." },
              { icon: <Globe className="text-purple-400 w-8 h-8 mb-6"/>, title: "Smart Fast Search", desc: "Fuzzy searching with instant typo correction. Type 'RIL' or 'Relaince', we'll snap you to the chart." },
              { icon: <BarChart2 className="text-pink-400 w-8 h-8 mb-6"/>, title: "TradingView Canvas", desc: "Lightweight chart integration offering smooth panning, zooming, and timeframe swaps." },
              { icon: <CheckCircle className="text-stockai-neon w-8 h-8 mb-6"/>, title: "Paper Trading", desc: "Test the AI's accuracy with our built-in virtual portfolio before risking actual capital." }
            ].map((feature, i) => (
              <motion.div 
                key={i} 
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.1, duration: 0.5 }}
                className="p-8 rounded-3xl bg-stockai-card border border-white/5 hover:border-stockai-neon/30 hover:bg-stockai-surface hover:-translate-y-2 transition-all duration-300 text-left group shadow-lg"
              >
                <div className="bg-stockai-bg inline-block p-4 rounded-2xl border border-white/5 group-hover:scale-110 group-hover:shadow-[0_0_20px_rgba(20,184,166,0.3)] transition-all">
                  {feature.icon}
                </div>
                <h3 className="text-2xl font-bold mt-6 mb-3">{feature.title}</h3>
                <p className="text-stockai-muted leading-relaxed text-lg">{feature.desc}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Stats Counter & Proof */}
      <section className="relative z-10 py-24 px-4 max-w-7xl mx-auto">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-8 text-center divide-x divide-white/10">
          <div>
            <div className="text-5xl md:text-6xl font-extrabold text-white mb-2 drop-shadow-[0_0_15px_rgba(255,255,255,0.3)]">87<span className="text-stockai-neon">%</span></div>
            <div className="text-stockai-muted font-medium tracking-wide">Win Rate (1H)</div>
          </div>
          <div>
            <div className="text-5xl md:text-6xl font-extrabold text-white mb-2">150<span className="text-stockai-neon">ms</span></div>
            <div className="text-stockai-muted font-medium tracking-wide">Data Latency</div>
          </div>
          <div>
            <div className="text-5xl md:text-6xl font-extrabold text-white mb-2">50<span className="text-stockai-neon">+</span></div>
            <div className="text-stockai-muted font-medium tracking-wide">ML Indicators</div>
          </div>
          <div>
            <div className="text-5xl md:text-6xl font-extrabold text-white mb-2">24<span className="text-stockai-neon">/7</span></div>
            <div className="text-stockai-muted font-medium tracking-wide">Risk Monitoring</div>
          </div>
        </div>

        {/* Testimonials */}
        <div className="mt-32 grid md:grid-cols-3 gap-6">
          {[
            { name: "Rahul S.", role: "Day Trader", quote: "The 5m timeframe signals caught the BankNifty reversal perfectly today. Paid for the year." },
            { name: "Priya M.", role: "Swing Trader", quote: "No confusing setup. Just type the stock, get the AI sentiment, verify the chart, and execute." },
            { name: "Vikram K.", role: "Options Buyer", quote: "Better UI than my broker. The risk contexts save me from taking trades in low liquidity zones." }
          ].map((t, i) => (
             <div key={i} className="p-8 bg-stockai-card rounded-2xl border border-white/5 relative hover:border-stockai-neon/20 transition-colors">
               <div className="flex gap-1 mb-6">
                  {[...Array(5)].map((_, j) => <Star key={j} className="w-5 h-5 fill-stockai-neon text-stockai-neon" />)}
               </div>
               <p className="text-white/90 text-lg mb-8 italic">"{t.quote}"</p>
               <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-full bg-gradient-to-tr from-stockai-neon to-cyan-500 shadow-glow" />
                  <div>
                    <div className="font-bold text-white text-lg">{t.name}</div>
                    <div className="text-stockai-muted">{t.role}</div>
                  </div>
               </div>
             </div>
          ))}
        </div>
      </section>

      {/* Pricing / Final CTA */}
      <section id="pricing" className="relative z-10 py-32 border-t border-white/5 bg-gradient-to-b from-stockai-bg to-[#030508] text-center px-4">
         <h2 className="text-5xl md:text-7xl font-bold tracking-tight mb-6">Stop Guessing. <br className="hidden md:block"/><span className="text-stockai-neon">Start Trading.</span></h2>
         <p className="text-xl text-stockai-muted mb-12 max-w-2xl mx-auto">Get exclusive terminal access today. No complicated onboarding. Enter your key, view the signals.</p>
         
         <button 
            onClick={() => navigate('/login')}
            className="group inline-flex items-center justify-center gap-3 px-12 py-6 rounded-full bg-stockai-neon text-black font-extrabold text-2xl hover:shadow-[0_0_50px_rgba(0,255,159,0.8)] hover:scale-105 transition-all duration-300"
          >
            Access Terminal Now
            <ChevronRight className="w-8 h-8 group-hover:translate-x-2 transition-transform" />
         </button>
      </section>

      {/* Footer */}
      <footer className="relative z-10 border-t border-white/10 bg-[#020305] py-12 px-8 text-center md:text-left">
         <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center gap-6">
            <div className="flex items-center gap-4">
              <Activity className="w-6 h-6 text-stockai-neon" />
              <div className="text-xl font-bold tracking-tighter">StockAI<span className="text-stockai-neon">Pro</span></div>
            </div>
            <div className="text-stockai-muted text-sm">
              &copy; 2026 StockAI Technologies. All rights reserved. <br className="md:hidden" />
              <span className="md:ml-2 text-white/50">Built for the Indian Markets.</span>
            </div>
            <div className="flex gap-6 text-sm font-medium text-stockai-muted">
              <a href="#" className="hover:text-white transition-colors">Privacy</a>
              <a href="#" className="hover:text-white transition-colors">Terms</a>
              <a href="#" className="hover:text-white transition-colors">Contact</a>
            </div>
         </div>
      </footer>
      
      <style dangerouslySetInnerHTML={{ __html: `
        @keyframes marquee {
          0% { transform: translateX(0%); }
          100% { transform: translateX(-100%); }
        }
      `}} />
    </div>
  );
};

export default Landing;
