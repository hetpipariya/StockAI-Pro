import React, { useState } from 'react';
import { useStore } from '../store/useStore';
import { useToast } from '../components/Toast';
import { Card, Badge, Button } from '../components/ui';
import ConfirmDialog from '../components/ConfirmDialog';

const toNumber = (value, fallback = 0) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const signalVariant = (signal) => {
  const value = String(signal || '').toUpperCase();
  if (value === 'BUY') return 'buy';
  if (value === 'SELL') return 'sell';
  return 'info';
};

export default function Signals() {
  const { signals, currentSignal, executeTrade, bundleLoading } = useStore();
  const { showToast } = useToast();
  const [confirmTrade, setConfirmTrade] = useState(null);

  const signalRows = signals.length ? signals : (currentSignal ? [currentSignal] : []);

  const handleExecuteConfirmed = async (signal) => {
    try {
      await executeTrade(signal);
      showToast(`Trade executed for ${signal.symbol}`, 'success');
    } catch (error) {
      showToast(error.message, 'error');
    } finally {
      setConfirmTrade(null);
    }
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-10">
      <h2 className="text-2xl font-bold text-white mb-4">Live Signals</h2>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {signalRows.map(signal => (
          <Card key={signal.id}>
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-lg font-bold text-white">{signal.symbol}</h3>
              <Badge variant={signalVariant(signal.signal)}>{String(signal.signal || 'HOLD').toUpperCase()}</Badge>
            </div>
            <div className="text-gray-400 mb-2">Price: ₹{toNumber(signal.price ?? signal.currentPrice, 0).toFixed(2)}</div>
            <div className="text-gray-400 mb-6 text-sm">Confidence: {toNumber(signal.confidence, 0).toFixed(1)}%</div>
            <Button 
              onClick={() => setConfirmTrade(signal)}
              disabled={bundleLoading}
              className="w-full"
            >
              Execute Trade
            </Button>
          </Card>
        ))}
        {signalRows.length === 0 && <p className="text-gray-400">No active signals.</p>}
      </div>

      <ConfirmDialog
        isOpen={!!confirmTrade}
        title="Execute Trade?"
        message={confirmTrade ? `Execute ${confirmTrade.signal} for ${confirmTrade.symbol} at ₹${toNumber(confirmTrade.price ?? confirmTrade.currentPrice, 0).toFixed(2)}?` : ''}
        isDestructive={true}
        confirmText="Execute"
        onConfirm={() => handleExecuteConfirmed(confirmTrade)}
        onCancel={() => setConfirmTrade(null)}
      />
    </div>
  );
}