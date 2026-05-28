import React from 'react';
import { Card, Badge, Button } from '../ui';

const toFinite = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const formatCurrency = (value) => {
  const parsed = toFinite(value);
  if (parsed === null) return '--';
  return `INR ${parsed.toFixed(2)}`;
};

const formatPercent = (value) => {
  const parsed = toFinite(value);
  if (parsed === null) return '--';
  const pct = parsed <= 1 ? parsed * 100 : parsed;
  return `${pct.toFixed(1)}%`;
};

const compactReasonList = (reasons = []) => {
  if (!Array.isArray(reasons) || reasons.length === 0) return ['No rejection reason available'];
  return reasons.filter(Boolean).slice(0, 3);
};

export default function TradeStatusPanel({
  symbol,
  decision,
  isLoading = false,
  error = null,
  compact = false,
  onRefresh,
}) {
  const status = String(decision?.decision?.status || 'BLOCKED').toUpperCase();
  const isReady = status === 'READY';
  const isAuthError = String(error || '').includes('401');

  const reasons = compactReasonList(decision?.decision?.reasons);
  const confidence = decision?.signal?.confidence;
  const trend = String(decision?.market_filter?.trend || 'SIDEWAYS').toUpperCase();
  const positionSize = toFinite(decision?.risk?.position_size);
  const maxLoss = decision?.risk?.max_loss;
  const rr = toFinite(decision?.risk?.risk_reward_ratio);
  const source = String(decision?.market_data?.data_source || 'UNKNOWN').toUpperCase();
  const latencyMs = toFinite(decision?.market_data?.latency_ms ?? decision?.market_data?.latency);

  if (compact) {
    return (
      <div className={`rounded-xl border p-3 ${isReady ? 'border-emerald-400/40 bg-emerald-500/5' : 'border-rose-400/35 bg-rose-500/5'}`}>
        <div className="flex items-center justify-between gap-2 mb-2">
          <p className="text-xs uppercase tracking-wide text-gray-400">Trade Decision</p>
          <Badge variant={isReady ? 'buy' : 'sell'}>{status}</Badge>
        </div>

        {isLoading && !decision ? (
          <p className="text-xs text-gray-400">Evaluating trade quality...</p>
        ) : null}

        {(!isLoading || decision) && error ? (
          <p className="text-xs text-rose-300">{isAuthError ? 'Auth Error - Reconnect Required' : error}</p>
        ) : null}

        {(!isLoading || decision) && !error && isReady ? (
          <div className="text-xs text-gray-200 space-y-1">
            <p>Trend: <span className="font-semibold text-emerald-300">{trend}</span></p>
            <p>Confidence: <span className="font-semibold text-white">{formatPercent(confidence)}</span></p>
            <p>Position: <span className="font-semibold text-white">{positionSize ?? '--'} shares</span></p>
          </div>
        ) : null}

        {(!isLoading || decision) && !error && !isReady ? (
          <div className="space-y-1">
            {[
              ...reasons,
              ...(reasons.length ? [] : ['Low confidence', 'Sideways market', 'No breakout']),
            ].slice(0, 3).map((reason) => (
              <p key={reason} className="text-xs text-rose-200">• {reason}</p>
            ))}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <Card className={isReady ? 'border-emerald-500/35 bg-emerald-500/5' : 'border-rose-500/35 bg-rose-500/5'}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-bold text-white">Trade Status</h3>
        <Badge variant={isReady ? 'buy' : 'sell'}>{status}</Badge>
      </div>

      <p className="text-sm text-gray-300 mb-3">{symbol || 'N/A'}</p>

      {isLoading && !decision ? (
        <p className="text-sm text-gray-300">Evaluating signal quality and risk checks...</p>
      ) : null}

      {(!isLoading || decision) && error ? (
        <p className="text-sm text-rose-300">{isAuthError ? 'Auth Error - Reconnect Required' : error}</p>
      ) : null}

      {(!isLoading || decision) && !error && isReady ? (
        <div className="space-y-2 text-sm text-gray-200">
          <p>Confidence: <span className="font-semibold text-white">{formatPercent(confidence)}</span></p>
          <p>Trend: <span className="font-semibold text-emerald-300">{trend}</span></p>
          <p>Position Size: <span className="font-semibold text-white">{positionSize ?? '--'} shares</span></p>
          <p>Max Loss: <span className="font-semibold text-rose-300">{formatCurrency(maxLoss)}</span></p>
          <p>Risk/Reward: <span className="font-semibold text-white">{rr === null ? '--' : rr.toFixed(2)}</span></p>
          <p>Data Source: <span className="font-semibold text-white">{source}</span></p>
        </div>
      ) : null}

      {(!isLoading || decision) && !error && !isReady ? (
        <div>
          <p className="text-sm text-rose-200 mb-2">No trade condition:</p>
          <div className="space-y-1">
            {[
              ...reasons,
              ...(reasons.length ? [] : ['Low confidence', 'Sideways market', 'No breakout']),
            ].slice(0, 3).map((reason) => (
              <p key={reason} className="text-sm text-rose-100">• {reason}</p>
            ))}
          </div>
        </div>
      ) : null}

      {onRefresh ? (
        <div className="mt-4">
          <Button size="sm" variant="secondary" onClick={onRefresh} className="w-full" disabled={isLoading} isLoading={isLoading} loadingText="Evaluating...">
            Re-evaluate Decision
          </Button>
        </div>
      ) : null}
    </Card>
  );
}
