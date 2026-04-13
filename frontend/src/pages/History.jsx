import React from 'react';
import { useStore } from '../store/useStore';

export default function History() {
  const { tradeHistory } = useStore();

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-white mb-4">Trade History</h2>
      
      <div className="bg-[#131520] border border-gray-800/50 rounded-2xl shadow-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead className="bg-gray-900/50 text-gray-400 text-sm uppercase tracking-wider">
              <tr>
                <th className="px-6 py-4">Symbol</th>
                <th className="px-6 py-4">Type</th>
                <th className="px-6 py-4">Entry / Exit</th>
                <th className="px-6 py-4">Profit/Loss</th>
                <th className="px-6 py-4">Date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/50 text-gray-200">
              {tradeHistory.length === 0 ? (
                <tr><td colSpan="5" className="px-6 py-8 text-center text-gray-500">No trade history.</td></tr>
              ) : (
                tradeHistory.map(trade => (
                  <tr key={trade.id} className="hover:bg-gray-800/20 transition-colors">
                    <td className="px-6 py-4 font-bold">{trade.symbol}</td>
                    <td className="px-6 py-4">
                      <span className={`px-2 py-1 rounded text-xs font-bold ${trade.type === 'BUY' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
                        {trade.type}
                      </span>
                    </td>
                    <td className="px-6 py-4 font-mono text-sm">
                      <span className="text-gray-400">₹{trade.entryPrice.toFixed(2)}</span>
                      <span className="mx-2 text-gray-600">→</span>
                      <span className="text-white">₹{trade.exitPrice.toFixed(2)}</span>
                    </td>
                    <td className={`px-6 py-4 font-bold ${trade.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {trade.pnl >= 0 ? '+' : ''}₹{trade.pnl.toFixed(2)}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-500">
                      {new Date(trade.timestamp).toLocaleString()}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
