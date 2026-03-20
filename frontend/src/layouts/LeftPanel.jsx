import React, { useState } from 'react';
import DataStreamPanel from '../components/DataStreamPanel/DataStreamPanel';
import WatchlistPanel from '../components/WatchlistPanel/WatchlistPanel';

export default function LeftSidebar({ symbol, setSymbol, snapshot, onQuickOrder }) {
  const [activeTab, setActiveTab] = useState('Market');

  return (
    <aside className="w-[260px] shrink-0 flex flex-col h-full bg-[#06090E] border-r border-white/5 shadow-[4px_0_24px_rgba(0,0,0,0.4)] z-20">
      
      {/* A. TOP TABS */}
      <div className="flex items-center px-1 pt-2 shrink-0 border-b border-white/5 bg-[#0B1017]/50 backdrop-blur-md">
        {['Market', 'Watchlist', 'Backtest'].map(tab => (
          <button 
            key={tab} 
            onClick={() => setActiveTab(tab)}
            className={`flex-1 text-[10px] font-mono uppercase py-2 transition-all hover:bg-white/5
              ${activeTab === tab 
                ? 'text-teal-400 border-b-2 border-teal-500 shadow-[0_4px_10px_-2px_rgba(20,184,166,0.3)] bg-gradient-to-t from-teal-500/10 to-transparent' 
                : 'text-slate-500 hover:text-slate-300 border-b-2 border-transparent'}`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* SCROLLABLE LEFT PANEL */}
      <div className="flex-1 overflow-y-auto custom-scrollbar flex flex-col">
        
        {activeTab === 'Market' && (
          <DataStreamPanel 
            selected={symbol} 
            onSelect={setSymbol} 
            snapshot={snapshot} 
            onQuickOrder={onQuickOrder} 
          />
        )}

        {activeTab === 'Watchlist' && (
          <WatchlistPanel 
            selected={symbol} 
            onSelect={setSymbol} 
            snapshot={snapshot} 
          />
        )}

        {activeTab === 'Backtest' && (
          <div className="flex flex-col items-center justify-center p-8 text-center text-slate-500 font-mono text-xs h-full">
            <svg className="w-8 h-8 mb-3 opacity-50 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" /></svg>
            Backtesting Engine Module Coming Soon
          </div>
        )}

      </div>
    </aside>
  );
}
