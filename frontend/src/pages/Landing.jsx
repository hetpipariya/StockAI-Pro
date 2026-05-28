import React from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRight,
  BarChart3,
  CheckCircle2,
  Command,
  Database,
  Layers,
  Radar,
  Shield,
  Sparkles,
  Timer,
  TrendingUp,
} from 'lucide-react';

const pillars = [
  {
    icon: Radar,
    title: 'Signal Ranking Engine',
    text: 'Every opportunity is scored and ranked by confidence before any action reaches your terminal.',
  },
  {
    icon: Shield,
    title: 'Risk Guardrails',
    text: 'Position sizing and stop maps are enforced through risk limits, not discretionary guesswork.',
  },
  {
    icon: Database,
    title: 'Unified Market Feed',
    text: 'Snapshots, candles, and indicators are synced into a single operational data layer.',
  },
  {
    icon: Layers,
    title: 'Execution Stack',
    text: 'From prediction to route decision, each stage is traceable so you can inspect before you deploy.',
  },
];

const stats = [
  { label: 'Avg Response', value: '< 120 ms' },
  { label: 'Monitored Symbols', value: '500+' },
  { label: 'Pipeline Health', value: '99.2%' },
  { label: 'Risk Compliance', value: 'High' },
];

const steps = [
  'Login and configure mode (paper or live).',
  'Select symbol and timeframe from command desk.',
  'Validate AI signal, confidence, and risk map.',
  'Route execution only when decision status is READY.',
];

export default function Landing() {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen overflow-x-hidden bg-[#040A16] text-slate-100">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_12%_0%,rgba(34,211,238,0.2),transparent_34%),radial-gradient(circle_at_88%_12%,rgba(16,185,129,0.18),transparent_36%)]" />
      <div className="pointer-events-none fixed inset-0 bg-[linear-gradient(rgba(148,163,184,0.06)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.06)_1px,transparent_1px)] bg-[size:34px_34px] opacity-[0.12]" />

      <header className="relative z-10 border-b border-white/10 backdrop-blur-xl bg-[#050D1F]/85">
        <div className="mx-auto max-w-7xl px-6 py-5 flex items-center justify-between gap-4">
          <button type="button" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })} className="flex items-center gap-3">
            <span className="h-10 w-10 rounded-xl bg-gradient-to-br from-cyan-400 to-emerald-400 flex items-center justify-center shadow-[0_10px_30px_rgba(16,185,129,0.35)]">
              <Command className="h-5 w-5 text-[#041019]" />
            </span>
            <span className="text-xl font-black tracking-tight text-white">StockAI Command</span>
          </button>

          <div className="hidden md:flex items-center gap-7 text-sm text-slate-400 font-semibold">
            <a href="#pillars" className="hover:text-cyan-300 transition-colors">Platform</a>
            <a href="#workflow" className="hover:text-cyan-300 transition-colors">Workflow</a>
            <a href="#metrics" className="hover:text-cyan-300 transition-colors">Metrics</a>
          </div>

          <button
            type="button"
            onClick={() => navigate('/login')}
            className="rounded-xl px-6 py-2.5 bg-[#00F5FF]/10 border border-[#00F5FF]/40 text-cyan-300 font-bold hover:bg-[#00F5FF]/15 transition flex items-center gap-2 shadow-[0_0_15px_rgba(0,245,255,0.15)]"
          >
            Enter Terminal
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      </header>

      <main className="relative z-10">
        <section className="mx-auto max-w-7xl px-6 pt-20 pb-14 lg:pt-24 lg:pb-20">
          <div className="grid lg:grid-cols-[1.1fr_0.9fr] gap-12 items-center">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full border border-cyan-400/40 bg-cyan-400/10 px-4 py-1.5 text-xs uppercase tracking-[0.18em] text-cyan-200 font-bold">
                <Sparkles className="h-3.5 w-3.5" />
                Institutional AI Workspace
              </div>
              <h1 className="mt-6 text-5xl lg:text-6xl font-black tracking-[-0.03em] leading-tight text-white">
                A New Trading Frontend
                <span className="block text-transparent bg-clip-text bg-gradient-to-r from-cyan-300 to-[#00FF9D] mt-1">Built For Command Clarity</span>
              </h1>
              <p className="mt-6 text-lg text-slate-400 max-w-2xl leading-relaxed">
                This interface is engineered as an execution desk, not a generic dashboard: signal quality, risk policy, and route state stay visible at every step.
              </p>

              <div className="mt-9 flex flex-col sm:flex-row gap-4">
                <button
                  type="button"
                  onClick={() => navigate('/login')}
                  className="rounded-2xl px-7 py-3.5 font-bold text-[#050816] bg-gradient-to-r from-[#00FF9D] to-[#00F5FF] shadow-[0_4px_25px_rgba(0,245,255,0.25)] hover:scale-[1.01] hover:opacity-95 transition-all"
                >
                  Launch Terminal Desk
                </button>
                <button
                  type="button"
                  onClick={() => document.getElementById('workflow')?.scrollIntoView({ behavior: 'smooth' })}
                  className="rounded-2xl px-7 py-3.5 border border-white/10 bg-white/[0.03] text-slate-200 font-semibold hover:bg-white/[0.06] hover:border-white/20 transition-all"
                >
                  See Workflow
                </button>
              </div>
            </div>

            <article className="rounded-3xl border border-white/10 bg-gradient-to-br from-[#0C1220] via-[#080E1B] to-[#060A14] p-5 shadow-[0_24px_55px_rgba(0,0,0,0.55)] hover:border-[#00F5FF]/25 transition-all">
              <div className="flex items-center justify-between text-xs uppercase tracking-[0.16em] text-slate-400">
                <span>Signal Console</span>
                <span className="text-emerald-300">Live Feed</span>
              </div>
              <div className="mt-4 rounded-2xl border border-white/10 bg-[#081425] p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-xl font-black text-white">RELIANCE</p>
                  <p className="text-sm text-emerald-300 font-semibold">BUY 81%</p>
                </div>
                <div className="mt-3 h-2 rounded-full bg-white/10 overflow-hidden">
                  <div className="h-full w-[81%] bg-gradient-to-r from-cyan-400 to-emerald-400" />
                </div>
                <div className="mt-4 grid grid-cols-3 gap-2 text-xs">
                  <div className="rounded-lg border border-white/10 bg-white/[0.03] p-2">
                    <p className="text-slate-500">Entry</p>
                    <p className="text-cyan-200 font-semibold">2845.20</p>
                  </div>
                  <div className="rounded-lg border border-white/10 bg-white/[0.03] p-2">
                    <p className="text-slate-500">Stop</p>
                    <p className="text-rose-300 font-semibold">2816.80</p>
                  </div>
                  <div className="rounded-lg border border-white/10 bg-white/[0.03] p-2">
                    <p className="text-slate-500">Target</p>
                    <p className="text-emerald-300 font-semibold">2911.00</p>
                  </div>
                </div>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
                <div className="rounded-xl border border-white/10 bg-[#081425] px-3 py-2">
                  <p className="text-slate-500">Decision</p>
                  <p className="text-white font-semibold">READY</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-[#081425] px-3 py-2">
                  <p className="text-slate-500">Risk State</p>
                  <p className="text-emerald-300 font-semibold">Within Limits</p>
                </div>
              </div>
            </article>
          </div>
        </section>

        <section id="pillars" className="mx-auto max-w-7xl px-6 py-16">
          <p className="text-xs uppercase tracking-[0.18em] text-cyan-200 font-bold">Platform Pillars</p>
          <h2 className="mt-3 text-4xl font-black text-white">A full terminal layer, not a basic chart page.</h2>
          <div className="mt-8 grid md:grid-cols-2 xl:grid-cols-4 gap-4">
            {pillars.map((item) => (
              <article key={item.title} className="rounded-2xl border border-white/10 bg-[#081221]/85 p-4">
                <item.icon className="h-6 w-6 text-cyan-300" />
                <h3 className="mt-3 text-lg font-bold text-white">{item.title}</h3>
                <p className="mt-2 text-sm text-slate-300 leading-relaxed">{item.text}</p>
              </article>
            ))}
          </div>
        </section>

        <section id="workflow" className="border-y border-white/10 bg-[#060E1C]/85">
          <div className="mx-auto max-w-7xl px-6 py-16">
            <p className="text-xs uppercase tracking-[0.18em] text-cyan-200 font-bold">Workflow</p>
            <h2 className="mt-3 text-4xl font-black text-white">How the desk runs from setup to execution.</h2>
            <div className="mt-8 grid md:grid-cols-2 gap-4">
              {steps.map((step, index) => (
                <article key={step} className="rounded-2xl border border-white/10 bg-[#071224] px-4 py-3">
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500 font-bold">Step {index + 1}</p>
                  <p className="mt-2 text-slate-100 font-medium">{step}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="metrics" className="mx-auto max-w-7xl px-6 py-16">
          <p className="text-xs uppercase tracking-[0.18em] text-cyan-200 font-bold">Operational Metrics</p>
          <h2 className="mt-3 text-4xl font-black text-white">Numbers you monitor before any live route.</h2>
          <div className="mt-8 grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {stats.map((item) => (
              <article key={item.label} className="rounded-2xl border border-white/10 bg-[#081221]/85 p-4">
                <p className="text-xs uppercase tracking-[0.14em] text-slate-500">{item.label}</p>
                <p className="mt-2 text-3xl font-black text-white">{item.value}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-6 pb-20">
          <div className="rounded-3xl border border-cyan-500/30 bg-gradient-to-r from-cyan-500/12 to-emerald-500/10 p-7 flex flex-col lg:flex-row items-start lg:items-center justify-between gap-6">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-cyan-200 font-bold">Activation</p>
              <h3 className="mt-2 text-3xl font-black text-white">Open the redesigned terminal now.</h3>
              <p className="mt-2 text-slate-300">Login, choose mode, and run the full command workflow from one interface.</p>
            </div>
            <button
              type="button"
              onClick={() => navigate('/login')}
              className="rounded-2xl bg-white text-[#06111d] px-7 py-3 font-black flex items-center gap-2"
            >
              Go to Login
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </section>
      </main>

      <footer className="relative z-10 border-t border-white/10 bg-[#050B17]">
        <div className="mx-auto max-w-7xl px-6 py-8 text-center text-slate-500 text-sm">
          <div className="flex items-center justify-center gap-2 text-white font-black text-xl">
            <TrendingUp className="h-5 w-5 text-cyan-300" />
            StockAI Command
          </div>
          <p className="mt-3">Trading involves risk. Use this system with your own position sizing and discipline.</p>
        </div>
      </footer>
    </div>
  );
}
