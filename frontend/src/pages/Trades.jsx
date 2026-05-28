import React, { useMemo, useState } from 'react';
import { BarChart3, Clock3, TrendingDown, TrendingUp } from 'lucide-react';
import { useStore } from '../store/useStore';
import { useResponsive } from '../hooks/useResponsive';
import { useToast } from '../components/Toast';
import { Card, Badge, Button } from '../components/ui';
import ConfirmDialog from '../components/ConfirmDialog';

const toNumber = (value, fallback = 0) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

export default function Trades() {
  const { activeTrades, closeTrade } = useStore();
  const breakpoint = useResponsive();
  const isMobile = breakpoint === 'mobile';
  const { showToast } = useToast();
  const [tradeToClose, setTradeToClose] = useState(null);

  const totals = useMemo(() => {
    const netPnl = activeTrades.reduce((acc, trade) => acc + toNumber(trade.pnl, 0), 0);
    const longs = activeTrades.filter((trade) => String(trade.type).toUpperCase() === 'BUY').length;
    const shorts = activeTrades.filter((trade) => String(trade.type).toUpperCase() === 'SELL').length;
    return { netPnl, longs, shorts };
  }, [activeTrades]);

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
    return (
      <Card className="!p-8 border-white/10 bg-[#081628]/90 text-center text-slate-400">
        <BarChart3 className="h-6 w-6 mx-auto mb-2" />
        <p>No active trades to display.</p>
      </Card>
    );
  }

  return (
    <div className="space-y-5 max-w-[1600px] mx-auto pb-10">
      <Card className="!p-4 border-cyan-500/20 bg-[radial-gradient(circle_at_top,_rgba(34,211,238,0.15),_rgba(8,17,32,0.9)_60%)]">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-slate-400 font-bold">Execution Book</p>
            <h2 className="mt-1 text-2xl font-black text-white">Active Trades</h2>
          </div>
          <div className="grid grid-cols-3 gap-2 text-xs">
            <div className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2">
              <p className="text-slate-500">Net PnL</p>
              <p className={`font-semibold ${totals.netPnl >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>{totals.netPnl >= 0 ? '+' : ''}₹{totals.netPnl.toFixed(2)}</p>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2">
              <p className="text-slate-500">Long</p>
              <p className="font-semibold text-cyan-200">{totals.longs}</p>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2">
              <p className="text-slate-500">Short</p>
              <p className="font-semibold text-cyan-200">{totals.shorts}</p>
            </div>
          </div>
        </div>
      </Card>

      {isMobile ? (
        <div className="space-y-3">
          {activeTrades.map((trade) => {
            const isPositive = toNumber(trade.pnl, 0) >= 0;
            return (
              <Card key={trade.id} className="!p-4 border-white/10 bg-[#081628]/90">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="text-lg font-black text-white">{trade.symbol}</h3>
                    <Badge variant={String(trade.type).toUpperCase() === 'BUY' ? 'buy' : 'sell'}>{trade.type}</Badge>
                  </div>
                  <p className={`text-lg font-bold ${isPositive ? 'text-emerald-300' : 'text-rose-300'}`}>
                    {isPositive ? '+' : ''}₹{toNumber(trade.pnl, 0).toFixed(2)}
                  </p>
                </div>

                <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                  <div className="rounded-lg border border-white/10 bg-white/[0.03] p-2">
                    <p className="text-slate-500">Entry</p>
                    <p className="font-mono text-white mt-1">₹{toNumber(trade.entryPrice, 0).toFixed(2)}</p>
                  </div>
                  <div className="rounded-lg border border-white/10 bg-white/[0.03] p-2">
                    <p className="text-slate-500">Current</p>
                    <p className="font-mono text-cyan-200 mt-1">₹{toNumber(trade.currentPrice, trade.entryPrice).toFixed(2)}</p>
                  </div>
                  <div className="rounded-lg border border-white/10 bg-white/[0.03] p-2">
                    <p className="text-slate-500">Stop</p>
                    <p className="font-mono text-rose-300 mt-1">₹{toNumber(trade.sl, 0).toFixed(2)}</p>
                  </div>
                  <div className="rounded-lg border border-white/10 bg-white/[0.03] p-2">
                    <p className="text-slate-500">Target</p>
                    <p className="font-mono text-emerald-300 mt-1">₹{toNumber(trade.tp, 0).toFixed(2)}</p>
                  </div>
                </div>

                <Button onClick={() => setTradeToClose(trade.id)} variant="danger" className="w-full mt-3">
                  Close Trade
                </Button>
              </Card>
            );
          })}
        </div>
      ) : (
        <Card className="!p-0 border-white/10 bg-[#081628]/90 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-white/[0.03] border-b border-white/10 text-slate-400 uppercase tracking-[0.12em] text-[11px]">
                <tr>
                  <th className="px-4 py-3">Symbol</th>
                  <th className="px-4 py-3">Direction</th>
                  <th className="px-4 py-3">Entry</th>
                  <th className="px-4 py-3">Current</th>
                  <th className="px-4 py-3">SL / TP</th>
                  <th className="px-4 py-3">PnL</th>
                  <th className="px-4 py-3">Action</th>
                </tr>
              </thead>
              <tbody>
                {activeTrades.map((trade) => {
                  const isPositive = toNumber(trade.pnl, 0) >= 0;
                  return (
                    <tr key={trade.id} className="border-b border-white/5 hover:bg-white/[0.02]">
                      <td className="px-4 py-3 font-semibold text-white">{trade.symbol}</td>
                      <td className="px-4 py-3">
                        <Badge variant={String(trade.type).toUpperCase() === 'BUY' ? 'buy' : 'sell'}>{trade.type}</Badge>
                      </td>
                      <td className="px-4 py-3 font-mono text-slate-200">₹{toNumber(trade.entryPrice, 0).toFixed(2)}</td>
                      <td className="px-4 py-3 font-mono text-cyan-200">₹{toNumber(trade.currentPrice, trade.entryPrice).toFixed(2)}</td>
                      <td className="px-4 py-3 font-mono text-xs space-y-1">
                        <div className="text-rose-300 inline-flex items-center gap-1"><TrendingDown className="h-3 w-3" /> ₹{toNumber(trade.sl, 0).toFixed(2)}</div>
                        <div className="text-emerald-300 inline-flex items-center gap-1"><TrendingUp className="h-3 w-3" /> ₹{toNumber(trade.tp, 0).toFixed(2)}</div>
                      </td>
                      <td className={`px-4 py-3 font-bold ${isPositive ? 'text-emerald-300' : 'text-rose-300'}`}>
                        {isPositive ? '+' : ''}₹{toNumber(trade.pnl, 0).toFixed(2)}
                      </td>
                      <td className="px-4 py-3">
                        <Button size="sm" onClick={() => setTradeToClose(trade.id)}>Close</Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="px-4 py-2.5 text-xs text-slate-500 border-t border-white/10 flex items-center gap-1.5">
            <Clock3 className="h-3.5 w-3.5" />
            Positions update in realtime from live price feed.
          </div>
        </Card>
      )}

      <ConfirmDialog
        isOpen={!!tradeToClose}
        title="Close Trade"
        message="Are you sure you want to close this trade immediately?"
        isDestructive
        confirmText="Yes, Close"
        onConfirm={() => handleCloseConfirm(tradeToClose)}
        onCancel={() => setTradeToClose(null)}
      />
    </div>
  );
}
