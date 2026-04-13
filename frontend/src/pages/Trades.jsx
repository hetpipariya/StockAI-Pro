import React, { useState } from 'react';
import { useStore } from '../store/useStore';
import { useResponsive } from '../hooks/useResponsive';
import { useToast } from '../components/Toast';
import { Card, Badge, Button } from '../components/ui';
import ConfirmDialog from '../components/ConfirmDialog';

export default function Trades() {
  const { activeTrades, closeTrade } = useStore();
  const breakpoint = useResponsive();
  const isMobile = breakpoint === 'mobile';
  const { showToast } = useToast();
  const [tradeToClose, setTradeToClose] = useState(null);

  const handleCloseConfirm = async (id) => {
    try {
      await closeTrade(id);
      showToast('Trade successfully closed!', 'success');
    } catch (error) {
      showToast(error.message, 'error');
    } finally {
      setTradeToClose(null);
    }
  };

  if (activeTrades.length === 0) {
     return <div className="text-white p-8 text-center text-gray-500">No active trades to display.</div>;
  }

  if (isMobile) {
    return (
      <div className="space-y-4 px-2 pb-10">
        <h2 className="text-xl font-bold text-white mb-2">Active Trades</h2>
        {activeTrades.map((trade) => (
          <Card key={trade.id}>
            <div className="flex justify-between items-start mb-4">
              <div>
                <h3 className="text-lg font-bold text-white">{trade.symbol}</h3>
                <Badge variant={trade.type === 'BUY' ? 'buy' : 'sell'}>{trade.type}</Badge>
              </div>
              <div className={`text-lg font-bold ${trade.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                ₹{trade.pnl.toFixed(2)}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 text-sm mb-4">
              <div>
                <span className="text-gray-400 block">Entry</span>
                <div className="font-mono text-white">₹{trade.entryPrice.toFixed(2)}</div>
              </div>
              <div>
                <span className="text-gray-400 block">SL</span>
                <div className="font-mono text-red-400">₹{trade.sl.toFixed(2)}</div>
              </div>
              <div>
                <span className="text-gray-400 block">TP</span>
                <div className="font-mono text-green-400">₹{trade.tp.toFixed(2)}</div>
              </div>
            </div>
            <Button onClick={() => setTradeToClose(trade.id)} variant="danger" className="w-full py-3 text-base min-h-[44px]">
              Close Trade
            </Button>
          </Card>
        ))}
        <ConfirmDialog
          isOpen={!!tradeToClose}
          title="Close Trade"
          message="Are you sure you want to close this trade immediately?"
          isDestructive={true}
          confirmText="Yes, Close"
          onConfirm={() => handleCloseConfirm(tradeToClose)}
          onCancel={() => setTradeToClose(null)}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-10">
      <h2 className="text-2xl font-bold text-white mb-4">Active Trades</h2>
      <Card className="overflow-x-auto">
        <table className="w-full text-left text-white border-collapse">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="p-4 font-medium text-gray-400">Symbol</th>
              <th className="p-4 font-medium text-gray-400">Type</th>
              <th className="p-4 font-medium text-gray-400">Entry</th>
              <th className="p-4 font-medium text-gray-400">SL/TP</th>
              <th className="p-4 font-medium text-gray-400">PnL</th>
              <th className="p-4 font-medium text-gray-400">Actions</th>
            </tr>
          </thead>
          <tbody>
            {activeTrades.map((trade) => (
              <tr key={trade.id} className="border-b border-gray-800/50 hover:bg-gray-800/20">
                <td className="p-4 font-bold">{trade.symbol}</td>
                <td className="p-4">
                   <Badge variant={trade.type === 'BUY' ? 'buy' : 'sell'}>{trade.type}</Badge>
                </td>
                <td className="p-4 font-mono w-28">₹{trade.entryPrice.toFixed(2)}</td>
                <td className="p-4 font-mono w-40 space-y-1">
                   <div className="text-red-400 text-xs">SL: ₹{trade.sl.toFixed(2)}</div>
                   <div className="text-green-400 text-xs">TP: ₹{trade.tp.toFixed(2)}</div>
                </td>
                <td className={`p-4 font-bold ${trade.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  ₹{trade.pnl.toFixed(2)}
                </td>
                <td className="p-4">
                   <Button onClick={() => setTradeToClose(trade.id)} variant="danger" size="sm">Close</Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      
      <ConfirmDialog
        isOpen={!!tradeToClose}
        title="Close Trade"
        message="Are you sure you want to close this trade immediately?"
        isDestructive={true}
        confirmText="Yes, Close"
        onConfirm={() => handleCloseConfirm(tradeToClose)}
        onCancel={() => setTradeToClose(null)}
      />
    </div>
  );
}