import React from 'react';
import { AlertTriangle, Gauge, Power, RefreshCw, ShieldAlert, Zap } from 'lucide-react';
import { useStore } from '../store/useStore';
import { Card } from '../components/ui';

export default function Settings() {
  const {
    isPaperTrading,
    toggleTradingMode,
    riskPercentage,
    setRiskPercentage,
    resetPortfolio,
    systemStatus,
    toggleSystemStatus,
  } = useStore();

  return (
    <div className="space-y-5 max-w-[1100px] pb-10">
      <Card className="!p-4 border-cyan-500/20 bg-[radial-gradient(circle_at_top,_rgba(34,211,238,0.15),_rgba(8,17,32,0.9)_60%)]">
        <p className="text-xs uppercase tracking-[0.18em] text-slate-400 font-bold">System Controls</p>
        <h2 className="mt-1 text-2xl font-black text-white">Settings & Risk Policy</h2>
      </Card>

      <section className="grid lg:grid-cols-2 gap-4">
        <Card className="!p-5 border-white/10 bg-[#081628]/90">
          <h3 className="text-lg font-black text-white">Trading Engine</h3>
          <p className="text-sm text-slate-400 mt-1">Control whether the strategy engine is actively routing decisions.</p>

          <div className="mt-5 rounded-xl border border-white/10 bg-white/[0.03] p-4 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className={`h-10 w-10 rounded-xl border flex items-center justify-center ${systemStatus ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300' : 'border-rose-500/40 bg-rose-500/10 text-rose-300'}`}>
                <Power className="h-4 w-4" />
              </div>
              <div>
                <p className="text-white font-semibold">{systemStatus ? 'Engine Running' : 'Engine Stopped'}</p>
                <p className="text-xs text-slate-500">{systemStatus ? 'Actively monitoring markets' : 'Execution pipeline paused'}</p>
              </div>
            </div>
            <button
              type="button"
              onClick={toggleSystemStatus}
              className={`rounded-lg px-4 py-2 text-sm font-semibold border transition ${systemStatus
                ? 'border-rose-500/40 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20'
                : 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20'}`}
            >
              {systemStatus ? 'Stop Engine' : 'Start Engine'}
            </button>
          </div>

          <div className="mt-4 rounded-xl border border-white/10 bg-white/[0.03] p-4 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className={`h-10 w-10 rounded-xl border flex items-center justify-center ${isPaperTrading ? 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300' : 'border-amber-500/40 bg-amber-500/10 text-amber-300'}`}>
                {isPaperTrading ? <ShieldAlert className="h-4 w-4" /> : <Zap className="h-4 w-4" />}
              </div>
              <div>
                <p className="text-white font-semibold">{isPaperTrading ? 'Paper Mode' : 'Live Mode'}</p>
                <p className="text-xs text-slate-500">{isPaperTrading ? 'Simulation routing enabled' : 'Live execution enabled'}</p>
              </div>
            </div>
            <button
              type="button"
              onClick={toggleTradingMode}
              className="rounded-lg px-4 py-2 text-sm font-semibold border border-cyan-500/40 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20"
            >
              Switch Mode
            </button>
          </div>
        </Card>

        <Card className="!p-5 border-white/10 bg-[#081628]/90">
          <h3 className="text-lg font-black text-white">Risk Per Trade</h3>
          <p className="text-sm text-slate-400 mt-1">Position sizing policy for future orders from the decision engine.</p>

          <div className="mt-6 rounded-xl border border-white/10 bg-white/[0.03] p-4">
            <div className="flex items-center justify-between gap-3 mb-3">
              <span className="inline-flex items-center gap-2 text-slate-300"><Gauge className="h-4 w-4 text-cyan-300" /> Current Risk</span>
              <span className="text-cyan-200 font-black text-xl">{riskPercentage}%</span>
            </div>

            <input
              type="range"
              min="1"
              max="10"
              step="0.5"
              value={riskPercentage}
              onChange={(event) => setRiskPercentage(Number(event.target.value))}
              className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-cyan-400"
            />

            <div className="mt-3 text-xs text-slate-500 flex items-center justify-between">
              <span>Conservative 1%</span>
              <span>Aggressive 10%</span>
            </div>
          </div>

          <div className="mt-4 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-100 inline-flex items-start gap-2">
            <AlertTriangle className="h-4 w-4 mt-0.5" />
            Higher risk increases drawdown potential. Validate policy in paper mode before live.
          </div>
        </Card>
      </section>

      <Card className="!p-5 border-rose-500/30 bg-gradient-to-r from-rose-500/10 to-[#081628]">
        <h3 className="text-lg font-black text-rose-300">Danger Zone</h3>
        <p className="text-sm text-slate-300 mt-1">This action closes all active trades and resets account capital to defaults.</p>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <div className="text-xs text-slate-500">Use only for full strategy reset and clean-state testing.</div>
          <button
            type="button"
            onClick={resetPortfolio}
            className="rounded-lg px-4 py-2 text-sm font-semibold border border-rose-500/40 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20 inline-flex items-center gap-2"
          >
            <RefreshCw className="h-4 w-4" />
            Reset Portfolio
          </button>
        </div>
      </Card>
    </div>
  );
}
