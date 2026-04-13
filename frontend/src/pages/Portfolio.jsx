import React from 'react';
import { useStore } from '../store/useStore';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { TrendingUp, BarChart2, Activity } from 'lucide-react';

const mockEquityData = Array.from({ length: 60 }, (_, i) => ({
  time: `Day ${i + 1}`,
  value: 100000 + (Math.random() - 0.3) * i * 300
}));

export default function Portfolio() {
  const { balance, winRate } = useStore();
  const currentCapital = balance + 14720; // Fake added return
  const returnPct = ((currentCapital - 100000) / 100000) * 100;

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-white mb-4">Portfolio Performance</h2>
      
      {/* Top Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <div className="bg-[#131520] border border-gray-800/50 p-6 rounded-2xl shadow-xl">
          <div className="text-sm text-gray-400 mb-2">Starting Capital</div>
          <div className="text-2xl font-bold text-white">₹1,00,000</div>
        </div>
        <div className="bg-[#131520] border border-gray-800/50 p-6 rounded-2xl shadow-xl relative overflow-hidden">
          <div className="absolute inset-0 bg-blue-500/5"></div>
          <div className="relative">
             <div className="text-sm text-gray-400 mb-2 flex items-center justify-between">
                <span>Current Capital</span>
                <span className="text-blue-400 flex"><TrendingUp className="w-4 h-4 mr-1"/></span>
             </div>
             <div className="text-2xl font-bold text-blue-400">₹{currentCapital.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</div>
          </div>
        </div>
        <div className="bg-[#131520] border border-gray-800/50 p-6 rounded-2xl shadow-xl">
          <div className="text-sm text-gray-400 mb-2">Return</div>
          <div className={`text-2xl font-bold ${returnPct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {returnPct >= 0 ? '+' : ''}{returnPct.toFixed(2)}%
          </div>
        </div>
        <div className="bg-[#131520] border border-gray-800/50 p-6 rounded-2xl shadow-xl">
          <div className="text-sm text-gray-400 mb-2">Max Drawdown</div>
          <div className="text-2xl font-bold text-red-400">7.2%</div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Equity Chart */}
        <div className="lg:col-span-2 bg-[#131520] border border-gray-800/50 p-6 rounded-2xl shadow-xl">
          <h3 className="text-lg font-bold text-white mb-6">Long-term Equity Curve</h3>
          <div className="h-[350px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={mockEquityData}>
                <defs>
                  <linearGradient id="equityColor" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" vertical={false} />
                <XAxis dataKey="time" stroke="#4b5563" tick={{fill: '#9ca3af', fontSize: 12}} dy={10} axisLine={false} tickLine={false} />
                <YAxis stroke="#4b5563" tick={{fill: '#9ca3af', fontSize: 12}} dx={-10} axisLine={false} tickLine={false} domain={['auto', 'auto']} tickFormatter={(value) => `₹${(value/1000)}k`} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#111827', borderColor: '#374151', borderRadius: '8px' }}
                  itemStyle={{ color: '#10b981' }}
                  formatter={(value) => [`₹${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`, 'Capital']}
                />
                <Area type="monotone" dataKey="value" stroke="#10b981" strokeWidth={3} fillOpacity={1} fill="url(#equityColor)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Trade Metrics */}
        <div className="bg-[#131520] border border-gray-800/50 p-6 rounded-2xl shadow-xl">
          <h3 className="text-lg font-bold text-white mb-6">Key Metrics</h3>
          <div className="space-y-6">
            <div className="flex items-center justify-between p-4 bg-gray-900/50 rounded-xl border border-gray-800/30">
               <div className="flex items-center"><Activity className="w-5 h-5 text-gray-500 mr-3" /><span className="text-gray-300 font-medium">Profit Factor</span></div>
               <span className="text-green-400 font-bold">1.39</span>
            </div>
            <div className="flex items-center justify-between p-4 bg-gray-900/50 rounded-xl border border-gray-800/30">
               <div className="flex items-center"><BarChart2 className="w-5 h-5 text-gray-500 mr-3" /><span className="text-gray-300 font-medium">Win Rate</span></div>
               <span className="text-blue-400 font-bold">{winRate}%</span>
            </div>
            <div className="flex items-center justify-between p-4 bg-gray-900/50 rounded-xl border border-gray-800/30">
               <div className="flex items-center"><TrendingUp className="w-5 h-5 text-gray-500 mr-3" /><span className="text-gray-300 font-medium">Average Trade</span></div>
               <span className="text-white font-bold">₹1,240.50</span>
            </div>
            <div className="flex items-center justify-between p-4 bg-gray-900/50 rounded-xl border border-gray-800/30">
               <div className="flex items-center"><Activity className="w-5 h-5 text-gray-500 mr-3" /><span className="text-gray-300 font-medium">Sharpe Ratio</span></div>
               <span className="text-white font-bold">2.1</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
