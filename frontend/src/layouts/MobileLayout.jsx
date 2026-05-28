import React from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { LayoutDashboard, Activity, BarChart2, Briefcase, History, Settings, CandlestickChart, Radio } from 'lucide-react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { useLivePrice } from '../context/LivePriceContext';

export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

export const navigation = [
  { name: 'Dashboard', href: '/dashboard', icon: LayoutDashboard },
  { name: 'Signals', href: '/signals', icon: Activity },
  { name: 'Trades', href: '/trades', icon: BarChart2 },
  { name: 'Portfolio', href: '/portfolio', icon: Briefcase },
  { name: 'History', href: '/history', icon: History },
  { name: 'Settings', href: '/settings', icon: Settings },
];

const BottomNavItem = ({ item }) => (
  <NavLink
    to={item.href}
    className={({ isActive }) =>
      cn(
        'flex flex-col items-center justify-center w-full h-full relative transition-colors',
        isActive ? 'text-cyan-300' : 'text-slate-500 hover:text-slate-300'
      )
    }
  >
    {({ isActive }) => (
      <>
        <item.icon className={cn('h-5 w-5 mb-1 flex-shrink-0', isActive ? 'text-cyan-300 drop-shadow-[0_0_8px_rgba(34,211,238,0.6)]' : '')} strokeWidth={isActive ? 2.5 : 2} />
        <span className={cn('text-[10px] font-bold tracking-wide', isActive ? 'text-cyan-300' : 'text-slate-500')}>{item.name}</span>
        {isActive && (
          <div className="absolute top-0 w-8 h-[3px] bg-cyan-400 rounded-b-full shadow-[0_2px_8px_rgba(34,211,238,0.8)]" />
        )}
      </>
    )}
  </NavLink>
);

export default function MobileLayout({ children }) {
  const { symbol, currentPrice, dataSource, connectionStatus, health, noLiveData } = useLivePrice();
  const location = useLocation();

  const normalizedHealth = String(health || 'STALE').toUpperCase();
  
  const healthLabel = connectionStatus === 'CONNECTING'
    ? 'CONNECTING'
    : (connectionStatus === 'CONNECTED' && normalizedHealth === 'LIVE' ? 'LIVE' : 'DISCONNECTED');

  const priceValue = Number.isFinite(Number(currentPrice)) && Number(currentPrice) > 0
    ? `₹${Number(currentPrice).toFixed(2)}`
    : '--';
  const sourceLabel = String(dataSource || 'UNKNOWN').toUpperCase();

  const statusTone = connectionStatus === 'CONNECTING'
    ? 'bg-amber-500/10 text-amber-300 border-amber-500/30 shadow-[0_0_15px_rgba(250,204,21,0.1)]'
    : (connectionStatus === 'CONNECTED' && normalizedHealth === 'LIVE'
      ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30 shadow-[0_0_15px_rgba(34,197,94,0.1)]'
      : 'bg-rose-500/10 text-rose-300 border-rose-500/30 shadow-[0_0_15px_rgba(239,68,68,0.1)]');
      
  const getPageTitle = () => {
     const match = navigation.find(n => location.pathname.startsWith(n.href));
     return match ? match.name : 'StockAI';
  };

  return (
    <div className="flex flex-col h-[100dvh] w-full bg-[#030914] text-white overflow-hidden font-sans">
      {/* Top Header */}
      <header className="flex h-16 shrink-0 items-center px-4 border-b border-white/10 bg-[#060E1D]/95 backdrop-blur-xl z-20 justify-between shadow-sm">
        <div className="flex items-center">
           <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center mr-3 shadow-lg shadow-cyan-500/20">
             <CandlestickChart className="h-5 w-5 text-white" />
           </div>
           <h1 className="text-lg font-bold bg-gradient-to-r from-cyan-300 to-blue-400 text-transparent bg-clip-text tracking-tight">
             {getPageTitle()}
           </h1>
        </div>
        <div className="flex items-center gap-2">
           <div className={`px-2.5 py-1 rounded-full text-[10px] font-bold tracking-wider border flex items-center ${statusTone}`}>
             <span className={`w-1.5 h-1.5 rounded-full mr-1.5 ${connectionStatus === 'CONNECTING' ? 'bg-amber-400 animate-pulse shadow-[0_0_8px_rgba(250,204,21,0.8)]' : (connectionStatus === 'CONNECTED' && normalizedHealth === 'LIVE' ? 'bg-emerald-500 animate-pulse shadow-[0_0_8px_rgba(34,197,94,0.8)]' : 'bg-rose-400 shadow-[0_0_8px_rgba(248,113,113,0.8)]')}`}></span>
             {healthLabel}
           </div>
           <div className="px-2 py-1 rounded-lg text-[10px] border border-cyan-500/30 bg-cyan-500/10 text-cyan-200 flex items-center gap-1">
             <Radio className="w-3 h-3" />
             <span>{symbol || 'N/A'}</span>
             <span>{priceValue}</span>
           </div>
        </div>
      </header>

      {/* Main Scrollable Content */}
      <main className="flex-1 w-full overflow-y-auto bg-[radial-gradient(circle_at_top,_rgba(6,182,212,0.14),_rgba(2,6,23,0.96)_45%),linear-gradient(180deg,_#020617,_#01040B)] p-4 pb-20 scrollbar-hide">
        <div className="mb-3 rounded-xl border border-white/10 bg-[#081120]/80 px-3 py-2 text-[11px] text-slate-400 flex items-center justify-between">
          <span>{sourceLabel}</span>
          {noLiveData ? <span className="text-rose-300">NO LIVE DATA</span> : <span className="text-emerald-300">FEED OK</span>}
        </div>
        {children}
      </main>

      {/* Bottom Navigation matches sidebar menu */}
      <nav className="shrink-0 h-[64px] bg-[#060E1D]/95 border-t border-white/10 backdrop-blur-xl flex items-center justify-around z-50">
        {navigation.map(item => (
          <BottomNavItem key={item.name} item={item} />
        ))}
      </nav>
    </div>
  );
}