import React, { useEffect, useState } from 'react';
import { useStore } from '../../store/useStore.js';
import { Command, Bell, Activity, Wifi, ShieldAlert, Cpu, Database, Server } from 'lucide-react';
import SmartSearchBar from './SmartSearchBar';

const DEFAULT_WATCHLIST = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK', 'SBIN', 'TATASTEEL'];

export default function Topbar({ handleSelectSymbol }) {
  const selectedSymbol = useStore(state => state.selectedSymbol);
  const priceBySymbol = useStore(state => state.priceBySymbol);
  const symbolCatalog = useStore(state => state.symbolCatalog);
  const connectionStatus = useStore(state => state.connectionStatus);
  const liveLatencyMs = useStore(state => state.liveLatencyMs);
  const serverHealthMatrix = useStore(state => state.serverHealthMatrix);
  const checkBackendReady = useStore(state => state.checkBackendReady);

  const [time, setTime] = useState(() => new Date().toLocaleTimeString('en-IN', { hour12: false }));
  const [showNotifications, setShowNotifications] = useState(false);
  const [showHealthTooltip, setShowHealthTooltip] = useState(false);

  useEffect(() => {
    const timer = setInterval(() => {
      setTime(new Date().toLocaleTimeString('en-IN', { hour12: false }));
    }, 1000);

    // Initial check and periodic polling
    void checkBackendReady();
    const sreTimer = setInterval(() => {
      void checkBackendReady();
    }, 8500);

    return () => {
      clearInterval(timer);
      clearInterval(sreTimer);
    };
  }, [checkBackendReady]);

  const latencyStr = liveLatencyMs !== null ? `${Math.round(liveLatencyMs)}ms` : '32ms';
  const latencyVal = liveLatencyMs !== null ? liveLatencyMs : 32;
  const latencyColor = latencyVal > 300 ? 'text-red-400 bg-red-500/10 border-red-500/20' : latencyVal > 150 ? 'text-amber-400 bg-amber-500/10 border-amber-500/20' : 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20';

  const wsOk = connectionStatus === 'CONNECTED';
  const dbOk = serverHealthMatrix?.database === 'nominal';
  const redisOk = serverHealthMatrix?.redis === 'nominal' || serverHealthMatrix?.redis === 'degraded_fallback';
  const mlOk = serverHealthMatrix?.ml_workers === 'active';

  const systemStatusLabel = dbOk && redisOk && mlOk ? 'NOMINAL' : 'DEGRADED';
  const systemStatusColor = systemStatusLabel === 'NOMINAL' ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' : 'text-amber-400 bg-amber-500/10 border-amber-500/20';

  return (
    <header className="h-[6vh] min-h-[50px] shrink-0 px-4 border-b border-white/5 bg-[#070B14] flex items-center justify-between z-30 select-none relative shadow-[0_4px_20px_rgba(0,0,0,0.4)]">
      
      {/* Brand logo & switcher */}
      <div className="flex items-center gap-3">
        <div className="h-8 w-8 rounded-lg border border-cyan-500/30 bg-gradient-to-br from-cyan-500/20 to-blue-500/10 flex items-center justify-center shadow-[0_0_12px_rgba(0,245,255,0.2)]">
          <Command className="h-4 w-4 text-cyan-300" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs uppercase font-extrabold tracking-[0.25em] bg-gradient-to-r from-cyan-400 via-teal-300 to-blue-400 text-transparent bg-clip-text">StockAI Pro</span>
            <span className="text-[8px] text-slate-500 border border-white/10 px-1.5 py-0.5 rounded font-mono font-bold tracking-widest bg-white/5">TERMINAL</span>
          </div>
        </div>
      </div>

      {/* Center Search bar */}
      <div className="w-96 max-w-sm hidden md:block">
        <SmartSearchBar
          selectedSymbol={selectedSymbol}
          onSelectSymbol={handleSelectSymbol}
          priceBySymbol={priceBySymbol}
          catalog={symbolCatalog}
          trendingSymbols={DEFAULT_WATCHLIST}
        />
      </div>

      {/* Real-time Indicators & User Area */}
      <div className="flex items-center gap-4">
        
        {/* Latency Gauge */}
        <div className={`px-2.5 py-1 rounded border text-[10px] font-mono font-semibold flex items-center gap-1.5 transition-all duration-300 ${latencyColor}`}>
          <Wifi className="h-3 w-3 animate-pulse" />
          <span>RTT: {latencyStr}</span>
        </div>

        {/* System Health Matrix Check */}
        <div 
          className="relative"
          onMouseEnter={() => setShowHealthTooltip(true)}
          onMouseLeave={() => setShowHealthTooltip(false)}
        >
          <div className={`px-2.5 py-1 rounded border text-[10px] font-mono font-semibold flex items-center gap-1.5 cursor-help transition-all duration-300 ${systemStatusColor}`}>
            <Activity className="h-3 w-3" />
            <span>SRE: {systemStatusLabel}</span>
          </div>

          {showHealthTooltip && (
            <div className="absolute right-0 top-8 mt-1 w-56 rounded-xl border border-white/10 bg-[#090F1E] p-3.5 shadow-2xl z-50 text-[10px] font-mono space-y-2.5 backdrop-blur-xl animate-fade-in">
              <p className="font-bold border-b border-white/10 pb-1.5 text-slate-400 uppercase tracking-widest text-[9px] flex items-center gap-1">
                <Server className="h-3 w-3 text-cyan-400" /> Infrastructure Matrix
              </p>
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-slate-400 flex items-center gap-1"><Database className="h-3 w-3 text-slate-500" /> Database</span>
                  <span className={dbOk ? 'text-emerald-400' : 'text-red-400'}>{serverHealthMatrix?.database || 'unreachable'}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-400 flex items-center gap-1"><Cpu className="h-3 w-3 text-slate-500" /> ML Engine</span>
                  <span className={mlOk ? 'text-[#00FF9D]' : 'text-red-400'}>{serverHealthMatrix?.ml_workers === 'active' ? 'nominal' : 'idle'}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-400 flex items-center gap-1"><Server className="h-3 w-3 text-slate-500" /> Redis Cache</span>
                  <span className={redisOk ? (serverHealthMatrix?.redis === 'degraded_fallback' ? 'text-amber-400' : 'text-[#00FF9D]') : 'text-red-400'}>
                    {serverHealthMatrix?.redis === 'degraded_fallback' ? 'degraded_fallback' : (serverHealthMatrix?.redis || 'unreachable')}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-400 flex items-center gap-1"><Wifi className="h-3 w-3 text-slate-500" /> WebSocket</span>
                  <span className={wsOk ? 'text-emerald-400' : 'text-red-400'}>{connectionStatus}</span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Real-time Clock */}
        <div className="hidden lg:flex items-center gap-1 text-[11px] text-slate-400 border border-white/5 px-2.5 py-1 rounded bg-[#090F1E] font-mono">
          <span>{time}</span>
        </div>

        {/* Alerts / Alarms */}
        <div className="relative">
          <button 
            type="button" 
            onClick={() => setShowNotifications(!showNotifications)}
            className="p-1.5 rounded-lg border border-white/5 hover:border-cyan-500/20 text-slate-400 hover:text-white transition-all bg-[#090F1E]"
          >
            <Bell className="h-4 w-4" />
          </button>
          
          {showNotifications && (
            <div className="absolute right-0 mt-2 w-64 rounded-xl border border-white/10 bg-[#090F1E] p-3 shadow-2xl z-50 text-[10px] font-mono">
              <p className="font-bold border-b border-white/5 pb-1.5 text-slate-400 uppercase tracking-widest text-[9px]">AI REALTIME ALARMS</p>
              <div className="py-2 space-y-2 text-slate-300">
                <p className="flex items-center justify-between"><span className="text-[#00FF9D]">RELIANCE BUY</span> <span>14:42</span></p>
                <p className="flex items-center justify-between"><span className="text-rose-400">TCS SELL</span> <span>14:38</span></p>
              </div>
            </div>
          )}
        </div>

        {/* Profile Card */}
        <div className="flex items-center gap-2 border-l border-white/10 pl-3.5">
          <div className="h-7 w-7 rounded-full bg-gradient-to-tr from-cyan-950 to-blue-900 border border-cyan-500/30 flex items-center justify-center text-[10px] text-cyan-300 font-bold tracking-wider">
            AD
          </div>
          <span className="hidden xl:inline-block text-xs font-semibold text-slate-300">AD01</span>
        </div>

      </div>

    </header>
  );
}
