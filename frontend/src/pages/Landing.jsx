import React from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Cpu,
  Database,
  Lock,
  Radar,
  Rocket,
  Shield,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Workflow,
  Zap,
} from 'lucide-react';
import '../styles/immersive-pages.css';

const commandStrip = [
  'Realtime Signal Bus',
  'Risk Gatekeeper',
  'Execution Router',
  'Portfolio Telemetry',
  'Regime Detection',
  'Latency-Aware Flow',
];

const stackCards = [
  {
    icon: Cpu,
    title: 'Signal Intelligence Core',
    detail:
      'Processes momentum, volatility structure, and trend context across intraday and swing windows.',
  },
  {
    icon: Radar,
    title: 'Confidence Scoring',
    detail:
      'Ranks each setup so weak opportunities are filtered out before any execution decision is allowed.',
  },
  {
    icon: Shield,
    title: 'Risk Envelope',
    detail:
      'Position size and stop placement are bounded by strict loss thresholds to defend capital first.',
  },
  {
    icon: Workflow,
    title: 'Order Pipeline',
    detail:
      'Normalizes signal-to-order flow with consistent checks before route, send, and post-trade tracking.',
  },
  {
    icon: Database,
    title: 'Market Data Layer',
    detail:
      'Streams normalized symbol snapshots and historical context for deterministic model behavior.',
  },
  {
    icon: Lock,
    title: 'Secure Control Plane',
    detail:
      'Token-secured sessions and guarded actions keep dashboard operations safe under live conditions.',
  },
];

const flowCards = [
  {
    step: '01',
    title: 'Configure Command Profile',
    text: 'Login, set mode, and define risk limits before the engine is armed.',
  },
  {
    step: '02',
    title: 'Scan and Grade Opportunities',
    text: 'The model continuously evaluates quality and blocks low-conviction noise.',
  },
  {
    step: '03',
    title: 'Route with Risk Controls',
    text: 'Only approved setups move through risk-gated execution routing.',
  },
  {
    step: '04',
    title: 'Monitor and Adapt',
    text: 'Live telemetry updates decisions as market state shifts across sessions.',
  },
];

const metrics = [
  { title: 'Profit Factor', value: '1.39', icon: TrendingUp },
  { title: 'Win Rate', value: '76%', icon: CheckCircle2 },
  { title: 'Drawdown', value: '< 7%', icon: ShieldCheck },
  { title: 'Auto Trades', value: '150+', icon: Zap },
];

const testimonials = [
  {
    quote:
      'I stopped forcing entries. The confidence layer keeps me patient and only surfaces cleaner opportunities.',
    person: 'Intraday Trader - Mumbai',
  },
  {
    quote:
      'What changed my process was consistency. Every trade now follows the same risk-first workflow.',
    person: 'Options Trader - Bengaluru',
  },
  {
    quote:
      'The dashboard gives full context: conviction, stop map, and route state in one screen.',
    person: 'Swing Trader - Ahmedabad',
  },
];

const faqItems = [
  {
    q: 'Can I start in paper mode first?',
    a: 'Yes. Paper mode is built in so you can validate system behavior and risk settings before live execution.',
  },
  {
    q: 'Does it support Indian market symbols?',
    a: 'Yes. The workflow is tuned for NSE/BSE style data, with symbol bundle support and intraday updates.',
  },
  {
    q: 'Will this replace my judgement completely?',
    a: 'No. It gives quantified decision support and disciplined execution controls. Final risk preference remains yours.',
  },
];

export default function Landing() {
  const navigate = useNavigate();
  const goLogin = () => navigate('/login');

  return (
    <div className="landing-vault-page min-h-screen text-slate-100 overflow-x-hidden">
      <div className="landing-vault-grid" aria-hidden="true" />
      <div className="landing-vault-glow landing-vault-glow-a" aria-hidden="true" />
      <div className="landing-vault-glow landing-vault-glow-b" aria-hidden="true" />
      <div className="landing-vault-glow landing-vault-glow-c" aria-hidden="true" />

      <nav className="vault-nav sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 py-5 flex items-center justify-between gap-4">
          <button
            type="button"
            onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
            className="flex items-center gap-3"
          >
            <span className="h-11 w-11 rounded-2xl bg-gradient-to-br from-cyan-400 to-blue-600 flex items-center justify-center shadow-[0_10px_35px_rgba(14,165,233,0.45)]">
              <TrendingUp className="h-6 w-6 text-white" />
            </span>
            <span className="text-2xl font-black tracking-tight text-white">
              StockAI <span className="text-cyan-300">Pro</span>
            </span>
          </button>

          <div className="hidden md:flex items-center gap-7 text-sm font-semibold text-slate-400">
            <a href="#stack" className="hover:text-cyan-300 transition-colors">Stack</a>
            <a href="#flow" className="hover:text-cyan-300 transition-colors">Flow</a>
            <a href="#proof" className="hover:text-cyan-300 transition-colors">Proof</a>
            <a href="#faq" className="hover:text-cyan-300 transition-colors">FAQ</a>
          </div>

          <button
            type="button"
            onClick={goLogin}
            className="px-6 py-2.5 rounded-xl text-sm font-bold text-white bg-gradient-to-r from-cyan-500 to-blue-600 hover:opacity-95 transition-all flex items-center gap-2 shadow-[0_8px_26px_rgba(14,165,233,0.35)]"
          >
            Login
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      </nav>

      <main className="relative z-10">
        <section className="max-w-7xl mx-auto px-6 pt-20 pb-16 lg:pt-24 lg:pb-20">
          <div className="grid lg:grid-cols-[1.1fr_1fr] gap-14 items-center">
            <div className="max-w-2xl">
              <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full border border-cyan-300/30 bg-cyan-400/10 text-cyan-200 text-xs font-bold tracking-[0.16em] uppercase mb-6">
                <Sparkles className="h-4 w-4" />
                Complete Trading Command Interface
              </div>

              <h1 className="text-4xl sm:text-5xl lg:text-6xl font-black tracking-[-0.03em] leading-tight">
                Algorithmic Command for
                <span className="block text-transparent bg-clip-text bg-gradient-to-r from-cyan-300 via-blue-300 to-indigo-300 mt-2">
                  Precision, Speed, and Protection
                </span>
              </h1>

              <p className="mt-6 text-slate-300 text-lg leading-relaxed max-w-xl">
                This is a full-stack decision cockpit: smarter signal grading, strict risk control, and realtime execution context for NSE and BSE-focused workflows.
              </p>

              <div className="mt-9 flex flex-col sm:flex-row gap-4 sm:items-center">
                <button
                  type="button"
                  onClick={goLogin}
                  className="px-7 py-3.5 rounded-2xl bg-gradient-to-r from-cyan-500 to-blue-600 text-white font-bold text-base shadow-[0_12px_30px_rgba(14,165,233,0.35)] hover:-translate-y-0.5 transition-transform flex items-center justify-center gap-2"
                >
                  Open Login
                  <Rocket className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  onClick={() => document.getElementById('flow')?.scrollIntoView({ behavior: 'smooth' })}
                  className="px-7 py-3.5 rounded-2xl border border-white/20 bg-white/5 text-slate-100 font-semibold hover:bg-white/10 transition-colors"
                >
                  Explore System Flow
                </button>
              </div>

              <div className="mt-8 flex flex-wrap gap-x-6 gap-y-3 text-sm text-slate-400">
                <span className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-emerald-400" /> Paper and Live Modes</span>
                <span className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-emerald-400" /> Dynamic Position Guard</span>
                <span className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-emerald-400" /> Realtime Decision Stream</span>
              </div>
            </div>

            <div className="vault-scene" aria-hidden="true">
              <article className="vault-scene-card vault-card-main">
                <p className="text-xs uppercase tracking-[0.2em] text-cyan-200/80 font-bold">Execution Grid</p>
                <h3 className="text-2xl font-black mt-2 text-white">Signal Integrity: HIGH</h3>
                <div className="mt-4 space-y-3 text-sm text-slate-200">
                  <div className="flex justify-between">
                    <span>Model Confidence</span>
                    <strong className="text-cyan-200">84.3%</strong>
                  </div>
                  <div className="h-2 rounded-full bg-cyan-900/40 overflow-hidden">
                    <span className="block h-full w-[84%] bg-gradient-to-r from-cyan-400 to-blue-500" />
                  </div>
                  <div className="grid grid-cols-2 gap-2 mt-2">
                    <span>Setup: Trend Continuation</span>
                    <span className="text-right text-emerald-300">Mode: Paper</span>
                  </div>
                </div>
              </article>

              <article className="vault-scene-card vault-card-side">
                <p className="text-xs uppercase tracking-[0.16em] text-slate-300">Current Signal</p>
                <div className="mt-2 text-white font-bold text-lg">BUY - RELIANCE</div>
                <div className="mt-3 text-sm text-slate-300 space-y-1">
                  <div className="flex justify-between"><span>Entry</span><span>2,845.20</span></div>
                  <div className="flex justify-between"><span>Stop</span><span>2,816.80</span></div>
                  <div className="flex justify-between"><span>Target</span><span>2,911.00</span></div>
                </div>
              </article>

              <article className="vault-scene-card vault-card-bottom">
                <p className="text-xs uppercase tracking-[0.16em] text-slate-300">Risk Envelope</p>
                <div className="mt-2 text-emerald-200 font-bold">Within Limits</div>
                <div className="mt-3 text-sm text-slate-300">Capital at Risk: 1.8%</div>
              </article>
            </div>
          </div>
        </section>

        <section className="vault-strip-wrap">
          <div className="vault-strip-track">
            {commandStrip.concat(commandStrip).map((item, idx) => (
              <span key={`${item}-${idx}`} className="vault-strip-item">
                <Activity className="h-4 w-4" />
                {item}
              </span>
            ))}
          </div>
        </section>

        <section id="stack" className="max-w-7xl mx-auto px-6 py-20">
          <div className="max-w-3xl">
            <p className="text-xs uppercase tracking-[0.2em] text-cyan-200 font-bold">System Stack</p>
            <h2 className="text-4xl font-black text-white mt-3">A complete operating layer for systematic trading.</h2>
          </div>

          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-5 mt-10">
            {stackCards.map((card) => (
              <article key={card.title} className="vault-stack-card">
                <card.icon className="h-7 w-7 text-cyan-300" />
                <h3 className="text-xl font-bold text-white mt-4">{card.title}</h3>
                <p className="text-slate-300 mt-3 leading-relaxed text-sm">{card.detail}</p>
              </article>
            ))}
          </div>
        </section>

        <section id="flow" className="border-y border-white/10 bg-[#070b13]/85">
          <div className="max-w-7xl mx-auto px-6 py-20">
            <div className="max-w-2xl">
              <p className="text-xs uppercase tracking-[0.2em] text-cyan-200 font-bold">Operational Flow</p>
              <h2 className="text-4xl font-black text-white mt-3">From login to controlled execution, every stage is explicit.</h2>
            </div>

            <div className="grid md:grid-cols-2 gap-5 mt-10">
              {flowCards.map((row) => (
                <article key={row.step} className="vault-flow-card">
                  <div className="vault-flow-step">{row.step}</div>
                  <h3 className="text-2xl font-bold text-white mt-4">{row.title}</h3>
                  <p className="text-slate-300 mt-3 leading-relaxed">{row.text}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="proof" className="max-w-7xl mx-auto px-6 py-20">
          <div className="grid lg:grid-cols-[1.05fr_1fr] gap-8">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-cyan-200 font-bold">Proof Layer</p>
              <h2 className="text-4xl font-black text-white mt-3">Metrics and trader feedback in one view.</h2>

              <div className="grid sm:grid-cols-2 gap-4 mt-8">
                {metrics.map((item) => (
                  <article key={item.title} className="vault-metric-card">
                    <item.icon className="h-5 w-5 text-cyan-300" />
                    <p className="text-4xl font-black text-white mt-2">{item.value}</p>
                    <p className="text-xs uppercase tracking-[0.15em] text-slate-400 mt-2">{item.title}</p>
                  </article>
                ))}
              </div>
            </div>

            <div className="space-y-4">
              {testimonials.map((item) => (
                <article key={item.person} className="vault-quote-card">
                  <p className="text-slate-200 leading-relaxed">"{item.quote}"</p>
                  <p className="text-cyan-200 text-sm font-semibold mt-5">{item.person}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="faq" className="max-w-5xl mx-auto px-6 py-20">
          <div className="text-center">
            <p className="text-xs uppercase tracking-[0.2em] text-cyan-200 font-bold">FAQ</p>
            <h2 className="text-4xl font-black text-white mt-3">Questions before activation.</h2>
          </div>

          <div className="mt-10 space-y-4">
            {faqItems.map((item) => (
              <details key={item.q} className="vault-faq-item group">
                <summary className="cursor-pointer list-none flex items-center justify-between gap-4 text-white font-bold">
                  {item.q}
                  <ArrowRight className="h-4 w-4 text-cyan-300 group-open:rotate-90 transition-transform" />
                </summary>
                <p className="text-slate-300 leading-relaxed mt-3">{item.a}</p>
              </details>
            ))}
          </div>

          <div className="mt-12 text-center">
            <button
              type="button"
              onClick={goLogin}
              className="px-9 py-4 rounded-full bg-white text-[#0a1220] font-black text-lg shadow-[0_16px_45px_rgba(255,255,255,0.2)] hover:translate-y-[-2px] transition-transform"
            >
              Continue to Login
            </button>
          </div>
        </section>

        <section className="max-w-6xl mx-auto px-6 pb-20">
          <div className="vault-final-card">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-cyan-200 font-bold">Ready to deploy</p>
              <h3 className="text-3xl font-black text-white mt-2">Your execution cockpit is one click away.</h3>
              <p className="text-slate-300 mt-3 max-w-2xl">
                Open the login page and start with paper mode, then move to live execution once your settings are validated.
              </p>
            </div>
            <button
              type="button"
              onClick={goLogin}
              className="vault-final-button"
            >
              Open Login
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </section>
      </main>

      <footer className="relative z-10 border-t border-white/10 bg-[#06090e]">
        <div className="max-w-7xl mx-auto px-6 py-10 text-center text-slate-400 text-sm">
          <div className="flex items-center justify-center gap-2 text-white font-black text-xl">
            <TrendingUp className="h-5 w-5 text-cyan-300" />
            StockAI Pro
          </div>
          <p className="mt-4 max-w-2xl mx-auto">
            Trading involves risk. This landing UI demonstrates product experience and workflow presentation.
          </p>
          <p className="mt-4 text-xs text-slate-500">© 2026 StockAI Pro</p>
        </div>
      </footer>
    </div>
  );
}
