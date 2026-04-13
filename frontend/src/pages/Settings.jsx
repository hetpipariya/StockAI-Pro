import React from 'react';
import { useStore } from '../store/useStore';
import { ShieldAlert, Zap, RefreshCw, Power } from 'lucide-react';

export default function Settings() {
  const { isPaperTrading, toggleTradingMode, riskPercentage, setRiskPercentage, resetPortfolio, systemStatus, toggleSystemStatus } = useStore();

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="bg-[#131520] border border-gray-800/50 p-6 rounded-2xl shadow-xl">
        <h3 className="text-xl font-bold text-white mb-6">Trading System Status</h3>
        
        <div className="flex items-center justify-between p-4 bg-gray-900/50 rounded-xl border border-gray-800/50 mb-6">
          <div className="flex items-center">
            <div className={`w-10 h-10 rounded-full flex items-center justify-center mr-4 ${systemStatus ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
              <Power className="h-5 w-5" />
            </div>
            <div>
              <p className="font-semibold text-white">AI Engine Status</p>
              <p className="text-sm text-gray-400">{systemStatus ? 'Actively monitoring markets' : 'System paused'}</p>
            </div>
          </div>
          <button 
            onClick={toggleSystemStatus}
            className={`px-6 py-2 rounded-lg font-medium transition-colors ${systemStatus ? 'bg-red-500/10 text-red-400 hover:bg-red-500/20 border border-red-500/30' : 'bg-green-500/10 text-green-400 hover:bg-green-500/20 border border-green-500/30'}`}
          >
            {systemStatus ? 'Stop Engine' : 'Start Engine'}
          </button>
        </div>

        <div className="flex items-center justify-between p-4 bg-gray-900/50 rounded-xl border border-gray-800/50">
          <div className="flex items-center">
            <div className={`w-10 h-10 rounded-full flex items-center justify-center mr-4 ${isPaperTrading ? 'bg-blue-500/20 text-blue-400' : 'bg-orange-500/20 text-orange-400'}`}>
              {isPaperTrading ? <ShieldAlert className="h-5 w-5" /> : <Zap className="h-5 w-5" />}
            </div>
            <div>
              <p className="font-semibold text-white">Execution Mode</p>
              <p className="text-sm text-gray-400">{isPaperTrading ? 'Simulated execution (Paper)' : 'Live Market Execution'}</p>
            </div>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input type="checkbox" className="sr-only peer" checked={!isPaperTrading} onChange={toggleTradingMode} />
            <div className="w-14 h-7 bg-gray-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-6 after:w-6 after:transition-all peer-checked:bg-orange-500"></div>
          </label>
        </div>
      </div>

      <div className="bg-[#131520] border border-gray-800/50 p-6 rounded-2xl shadow-xl">
        <h3 className="text-xl font-bold text-white mb-6">Risk Management</h3>
        <div className="mb-8">
          <div className="flex justify-between text-sm mb-2">
             <span className="text-gray-400">Risk per Trade</span>
             <span className="text-blue-400 font-bold">{riskPercentage}%</span>
          </div>
          <input 
            type="range" 
            min="1" max="10" step="0.5" 
            value={riskPercentage} 
            onChange={(e) => setRiskPercentage(Number(e.target.value))}
            className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
          />
          <p className="text-xs text-gray-500 mt-2">Adjusting this will change position sizing on future trades.</p>
        </div>
      </div>

      <div className="bg-[#131520] border border-gray-800/50 p-6 rounded-2xl shadow-xl border-red-500/10">
        <h3 className="text-xl font-bold text-red-400 mb-6">Danger Zone</h3>
        <div className="flex items-center justify-between">
           <div>
             <p className="font-semibold text-white">Reset Account</p>
             <p className="text-sm text-gray-400">Close all trades and reset balance to default.</p>
           </div>
           <button 
             onClick={resetPortfolio}
             className="px-4 py-2 bg-red-500/10 text-red-500 rounded-lg hover:bg-red-500/20 border border-red-500/30 transition-colors flex items-center"
           >
             <RefreshCw className="w-4 h-4 mr-2" /> Reset
           </button>
        </div>
      </div>
    </div>
  );
}
