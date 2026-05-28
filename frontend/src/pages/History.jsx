import React, { useEffect, useState } from 'react';
import { Clock3, FileClock, Filter, TrendingDown, TrendingUp } from 'lucide-react';
import { TradeService } from '../api/services/trade.service.js';
import { Card } from '../components/ui';

const mapJournalRows = (payload) => {
  const raw = payload?.trades ?? payload?.data?.trades ?? [];
  if (!Array.isArray(raw)) return [];
  return raw.map((row) => ({
    id: row.id,
    symbol: String(row.symbol || '—').toUpperCase(),
    direction: String(row.direction || '—').toUpperCase(),
    price: Number(row.price),
    pnl: row.pnl != null ? Number(row.pnl) : null,
    event: String(row.event || row.status || '—'),
    timestamp: row.timestamp || '',
  }));
};

export default function History() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const payload = await TradeService.getJournal(100);
        if (!cancelled) {
          setRows(mapJournalRows(payload));
        }
      } catch (e) {
        if (!cancelled) {
          setError(e?.message || 'Could not load trade journal');
          setRows([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="space-y-5 max-w-[1600px] mx-auto pb-10">
      <Card className="!p-4 border-cyan-500/20 bg-[radial-gradient(circle_at_top,_rgba(34,211,238,0.15),_rgba(8,17,32,0.9)_60%)]">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-slate-400 font-bold">Trade Journal</p>
            <h2 className="mt-1 text-2xl font-black text-white">Execution History</h2>
          </div>
          <div className="inline-flex items-center gap-2 text-xs text-slate-400 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-1.5">
            <Filter className="h-3.5 w-3.5" />
            Last 100 events
          </div>
        </div>
      </Card>

      {error ? (
        <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-amber-100 text-sm">
          {error}
        </div>
      ) : null}

      <Card className="!p-0 border-white/10 bg-[#081628]/90 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead className="bg-white/[0.03] text-slate-400 text-[11px] uppercase tracking-[0.14em] border-b border-white/10">
              <tr>
                <th className="px-4 py-3">Symbol</th>
                <th className="px-4 py-3">Direction</th>
                <th className="px-4 py-3">Price</th>
                <th className="px-4 py-3">PnL</th>
                <th className="px-4 py-3">Event</th>
                <th className="px-4 py-3">Time</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5 text-slate-200 text-sm">
              {loading ? (
                <tr>
                  <td colSpan="6" className="px-6 py-8 text-center text-slate-500">Loading journal...</td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan="6" className="px-6 py-8 text-center text-slate-500">No trade journal entries yet.</td>
                </tr>
              ) : (
                rows.map((trade) => {
                  const isBuy = trade.direction === 'BUY' || trade.direction === 'LONG';
                  const pnlKnown = trade.pnl != null;
                  const pnlPositive = Number(trade.pnl) >= 0;

                  return (
                    <tr key={trade.id} className="hover:bg-white/[0.02] transition-colors">
                      <td className="px-4 py-3 font-semibold text-white">{trade.symbol}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-[11px] font-bold ${isBuy ? 'bg-emerald-500/15 text-emerald-300' : 'bg-rose-500/15 text-rose-300'}`}>
                          {isBuy ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                          {trade.direction}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-cyan-200">
                        {Number.isFinite(trade.price) ? `₹${trade.price.toFixed(2)}` : '—'}
                      </td>
                      <td className={`px-4 py-3 font-semibold ${!pnlKnown ? 'text-slate-500' : (pnlPositive ? 'text-emerald-300' : 'text-rose-300')}`}>
                        {pnlKnown ? `${pnlPositive ? '+' : ''}₹${Number(trade.pnl).toFixed(2)}` : '—'}
                      </td>
                      <td className="px-4 py-3 text-slate-300 max-w-[220px] truncate" title={trade.event}>{trade.event}</td>
                      <td className="px-4 py-3 text-slate-500 text-xs">
                        {trade.timestamp ? new Date(trade.timestamp).toLocaleString() : '—'}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        <div className="px-4 py-2.5 border-t border-white/10 text-xs text-slate-500 flex items-center gap-1.5">
          <Clock3 className="h-3.5 w-3.5" />
          Journal records reflect backend trade lifecycle updates.
        </div>
      </Card>

      {!loading && rows.length > 0 ? (
        <div className="grid md:grid-cols-3 gap-3">
          <Card className="!p-4 border-white/10 bg-[#081628]/90">
            <p className="text-xs uppercase tracking-[0.12em] text-slate-500">Total Entries</p>
            <p className="mt-2 text-2xl font-black text-white">{rows.length}</p>
          </Card>
          <Card className="!p-4 border-white/10 bg-[#081628]/90">
            <p className="text-xs uppercase tracking-[0.12em] text-slate-500">Profitable Events</p>
            <p className="mt-2 text-2xl font-black text-emerald-300">{rows.filter((item) => item.pnl != null && item.pnl >= 0).length}</p>
          </Card>
          <Card className="!p-4 border-white/10 bg-[#081628]/90">
            <p className="text-xs uppercase tracking-[0.12em] text-slate-500">Latest Event</p>
            <p className="mt-2 text-sm font-semibold text-cyan-200 inline-flex items-center gap-1.5">
              <FileClock className="h-4 w-4" />
              {rows[0]?.symbol || '—'}
            </p>
          </Card>
        </div>
      ) : null}
    </div>
  );
}
