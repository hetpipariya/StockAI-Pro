import React from 'react';
import { Card } from '../ui/Card';
import { Wallet, TrendingUp, Target, Activity } from 'lucide-react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

const icons = {
  'Total Equity': Wallet,
  'Today P&L': TrendingUp,
  'Win Rate': Target,
  'Active Trades': Activity,
};

const colors = {
  'Total Equity': 'text-blue-400 bg-blue-500/10 border-blue-500/20',
  'Today P&L': 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  'Win Rate': 'text-purple-400 bg-purple-500/10 border-purple-500/20',
  'Active Trades': 'text-amber-400 bg-amber-500/10 border-amber-500/20',
};

const KpiCards = ({ kpidata }) => {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-5 xl:gap-6">
      {kpidata.map(stat => {
        const Icon = icons[stat.label] || Activity;
        const colorClass = colors[stat.label] || 'text-gray-400 bg-gray-500/10 border-gray-500/20';
        
        return (
          <div 
            key={stat.label} 
            className="flex flex-col relative overflow-hidden bg-gradient-to-br from-[#131627] to-[#0A0D18] border border-gray-800/60 p-4 md:p-6 rounded-[1.25rem] shadow-lg transition-all duration-300 hover:shadow-2xl hover:border-gray-700/80 group"
          >
            <div className="absolute -top-10 -right-10 w-24 h-24 bg-white/[0.01] rounded-full blur-2xl group-hover:bg-white/[0.03] transition-all"/>
            
            <div className="flex flex-col-reverse sm:flex-row sm:items-start sm:justify-between gap-3 mb-3 md:mb-6 relative z-10 w-full">
              <h3 className="text-gray-400 font-medium text-[10px] sm:text-xs md:text-sm tracking-wide uppercase mt-1 sm:mt-0">{stat.label}</h3>
              <div className={cn("w-8 h-8 md:w-11 md:h-11 rounded-[0.6rem] md:rounded-xl flex items-center justify-center border shadow-inner self-start", colorClass)}>
                <Icon className="w-4 h-4 md:w-5 md:h-5" />
              </div>
            </div>
            
            <div className="flex items-baseline gap-2 relative z-10">
               <div className="text-xl sm:text-2xl md:text-3xl xl:text-4xl font-extrabold text-white tracking-tight">
                 {stat.value}
               </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};
export default KpiCards;