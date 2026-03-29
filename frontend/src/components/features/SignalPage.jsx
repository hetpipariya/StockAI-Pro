import React, { useMemo } from 'react';

const toNumber = (value, fallback = null) => {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
};

const formatPrice = (value) => {
  const num = toNumber(value, null);
  if (num == null) return '--';
  return num.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

export default function SignalPage({ signal, confidence, currentPrice, target, stopLoss, regime, explanation, symbol }) {
  const safeSignal = String(signal || 'HOLD').toUpperCase();
  const safeConfidence = Math.max(0, Math.min(100, Math.round(toNumber(confidence, 0) || 0)));
  const entry = toNumber(currentPrice, 0) || 0;
  const tp = toNumber(target, entry) || entry;
  const sl = toNumber(stopLoss, entry) || entry;

  const analytics = useMemo(() => {
    const direction = safeSignal === 'SELL' ? -1 : 1;
    const reward = Math.max(0, (tp - entry) * direction);
    const risk = Math.max(0, (entry - sl) * direction);
    const rr = risk > 0 ? (reward / risk).toFixed(2) : '--';

    return {
      reward,
      risk,
      rr,
      trend:
        safeSignal === 'BUY'
          ? 'Bullish momentum'
          : safeSignal === 'SELL'
            ? 'Bearish momentum'
            : 'Sideways / neutral',
    };
  }, [entry, sl, safeSignal, tp]);

  const signalClass =
    safeSignal === 'BUY' ? 'buy' : safeSignal === 'SELL' ? 'sell' : 'hold';

  return (
    <section className="mobile-signal-page" aria-label="Signal details page">
      <div className="mobile-signal-page-head">
        <p>{symbol || 'SYMBOL'}</p>
        <h2 className={`mobile-signal-page-title ${signalClass}`}>{safeSignal}</h2>
      </div>

      <div className="mobile-signal-page-confidence">
        <span>AI Confidence</span>
        <strong>{safeConfidence}%</strong>
        <div className="mobile-signal-page-track" aria-hidden="true">
          <div className={`mobile-signal-page-fill ${signalClass}`} style={{ width: `${safeConfidence}%` }} />
        </div>
      </div>

      <div className="mobile-signal-page-grid">
        <article>
          <label>Entry</label>
          <strong>INR {formatPrice(entry)}</strong>
        </article>
        <article>
          <label>Target</label>
          <strong className="up">INR {formatPrice(tp)}</strong>
        </article>
        <article>
          <label>Stop Loss</label>
          <strong className="down">INR {formatPrice(sl)}</strong>
        </article>
        <article>
          <label>Risk / Reward</label>
          <strong>{analytics.rr === '--' ? '--' : `1 : ${analytics.rr}`}</strong>
        </article>
        <article>
          <label>Reward</label>
          <strong className="up">INR {formatPrice(analytics.reward)}</strong>
        </article>
        <article>
          <label>Risk</label>
          <strong className="down">INR {formatPrice(analytics.risk)}</strong>
        </article>
      </div>

      <div className="mobile-signal-page-trend">
        <span>Trend</span>
        <strong>{regime || analytics.trend}</strong>
      </div>

      <div className="mobile-signal-page-reasoning">
        <h3>AI Reasoning</h3>
        <p>{explanation || 'The model combines momentum, trend, and volatility signals before generating this setup.'}</p>
      </div>
    </section>
  );
}
