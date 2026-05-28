import React, { useMemo } from 'react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { Activity, BarChart3, Landmark, Shield, TrendingUp } from 'lucide-react';
import { useStore } from '../store/useStore';
import { Card } from '../components/ui';

const buildEquityData = (baseCapital, todaysPnL) => {
  const baseline = Number(baseCapital) || 100000;
  const drift = Number(todaysPnL) || 0;
  return Array.from({ length: 45 }, (_, index) => {
    const trend = baseline + (index * 240) + (Math.sin(index / 2.5) * 320);
    const noise = Math.cos(index / 3) * 180;
    const value = trend + noise + (drift * 0.25);
    return {
      time: `D${index + 1}`,
      value: Math.max(1000, Math.round(value)),
    };
  });
};

export default function Portfolio() {
  const { balance, winRate, todaysPnL, activeTrades } = useStore();
  const openingCapital = 100000;
  const currentCapital = Number(balance) || openingCapital;
  const returnPct = ((currentCapital - openingCapital) / openingCapital) * 100;
  const equityData = useMemo(() => buildEquityData(currentCapital, todaysPnL), [currentCapital, todaysPnL]);
  const grossExposure = useMemo(
    () => activeTrades.reduce((acc, trade) => acc + (Number(trade.entryPrice) * Number(trade.size || 1)), 0),
    [activeTrades],
  );

  return (
    <div className="space-y-5 max-w-[1600px] mx-auto pb-10">
      <Card className="!p-4 border-cyan-500/20 bg-[radial-gradient(circle_at_top,_rgba(34,211,238,0.15),_rgba(8,17,32,0.9)_60%)]">
        <p className="text-xs uppercase tracking-[0.18em] text-slate-400 font-bold">Portfolio Intelligence</p>
        <h2 className="mt-1 text-2xl font-black text-white">Capital & Performance</h2>
      </Card>

      <section className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
        <Card className="!p-4 border-white/10 bg-[#081628]/90">
          <p className="text-xs uppercase tracking-[0.12em] text-slate-500">Starting Capital</p>
          <p className="mt-2 text-2xl font-black text-white">₹{openingCapital.toLocaleString('en-IN')}</p>
        </Card>
        <Card className="!p-4 border-white/10 bg-[#081628]/90">
          <p className="text-xs uppercase tracking-[0.12em] text-slate-500">Current Capital</p>
          <p className="mt-2 text-2xl font-black text-cyan-200">₹{currentCapital.toLocaleString('en-IN')}</p>
        </Card>
        <Card className="!p-4 border-white/10 bg-[#081628]/90">
          <p className="text-xs uppercase tracking-[0.12em] text-slate-500">Return</p>
          <p className={`mt-2 text-2xl font-black ${returnPct >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>
            {returnPct >= 0 ? '+' : ''}{returnPct.toFixed(2)}%
          </p>
        </Card>
        <Card className="!p-4 border-white/10 bg-[#081628]/90">
          <p className="text-xs uppercase tracking-[0.12em] text-slate-500">Gross Exposure</p>
          <p className="mt-2 text-2xl font-black text-white">₹{grossExposure.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</p>
        </Card>
      </section>

      <section className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_360px] gap-4">
        <Card className="!p-5 border-white/10 bg-[#081628]/90">
          <div className="flex items-center justify-between gap-3 mb-4">
            <div>
              <p className="text-xs uppercase tracking-[0.12em] text-slate-500">Equity Curve</p>
              <h3 className="text-lg font-black text-white mt-1">Portfolio Trajectory</h3>
            </div>
            <span className="text-xs rounded-full border border-cyan-500/30 bg-cyan-500/10 text-cyan-200 px-3 py-1">45 Sessions</span>
          </div>

          <div className="h-[360px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={equityData}>
                <defs>
                  <linearGradient id="portfolioEquity" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#22d3ee" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="#22d3ee" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.18)" vertical={false} />
                <XAxis dataKey="time" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(value) => `₹${Math.round(value / 1000)}k`} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#081628',
                    border: '1px solid rgba(148,163,184,0.22)',
                    borderRadius: '10px',
                    color: '#e2e8f0',
                  }}
                  formatter={(value) => [`₹${Number(value).toLocaleString('en-IN')}`, 'Capital']}
                />
                <Area type="monotone" dataKey="value" stroke="#22d3ee" strokeWidth={2.5} fill="url(#portfolioEquity)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card className="!p-5 border-white/10 bg-[#081628]/90">
          <p className="text-xs uppercase tracking-[0.12em] text-slate-500">Performance Matrix</p>
          <h3 className="text-lg font-black text-white mt-1">Desk Metrics</h3>

          <div className="mt-4 space-y-3">
            <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 flex items-center justify-between">
              <span className="inline-flex items-center gap-2 text-slate-300"><TrendingUp className="h-4 w-4 text-emerald-300" /> Today PnL</span>
              <span className={`font-semibold ${Number(todaysPnL) >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>{Number(todaysPnL) >= 0 ? '+' : ''}₹{Number(todaysPnL || 0).toFixed(2)}</span>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 flex items-center justify-between">
              <span className="inline-flex items-center gap-2 text-slate-300"><BarChart3 className="h-4 w-4 text-cyan-300" /> Win Rate</span>
              <span className="font-semibold text-cyan-200">{Number(winRate || 0).toFixed(1)}%</span>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 flex items-center justify-between">
              <span className="inline-flex items-center gap-2 text-slate-300"><Landmark className="h-4 w-4 text-blue-300" /> Open Positions</span>
              <span className="font-semibold text-white">{activeTrades.length}</span>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 flex items-center justify-between">
              <span className="inline-flex items-center gap-2 text-slate-300"><Shield className="h-4 w-4 text-amber-300" /> Risk Stance</span>
              <span className="font-semibold text-amber-200">Controlled</span>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 flex items-center justify-between">
              <span className="inline-flex items-center gap-2 text-slate-300"><Activity className="h-4 w-4 text-violet-300" /> Volatility Mode</span>
              <span className="font-semibold text-violet-200">Adaptive</span>
            </div>
          </div>
        </Card>
      </section>
    </div>
  );
}
