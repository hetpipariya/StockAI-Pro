import React, { memo, useMemo, useState } from 'react';
import { Card } from '../ui/Card';
import { SkeletonCard } from '../ui/Skeleton';
import ErrorBoundary from '../ErrorBoundary';
import { useAppContext } from '../../context/AppContext';
import { useAuth } from '../../context/AuthContext';
import { useToast } from '../ui/Toast';
import { api } from '../../api/api';
import ErrorState from '../ui/ErrorState';
import NewsPanel from './NewsPanel';

const getFirstNumeric = (source, keys) => {
  for (const key of keys) {
    const value = Number(source?.[key]);
    if (Number.isFinite(value)) return value;
  }
  return null;
};

const formatCurrency = (value) => {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return 'NA';
  return `INR ${amount.toLocaleString('en-IN', { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`;
};

const getTradeStatus = (confidence) => {
  const score = Number(confidence) || 0;
  if (score >= 75) {
    return { label: 'HIGH PROBABILITY', color: '#22c55e', bg: 'rgba(34, 197, 94, 0.16)', border: 'rgba(34, 197, 94, 0.35)' };
  }
  if (score >= 55) {
    return { label: 'SETUP FORMING', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.15)', border: 'rgba(245, 158, 11, 0.32)' };
  }
  return { label: 'LOW CONFIDENCE', color: '#ef4444', bg: 'rgba(239, 68, 68, 0.15)', border: 'rgba(239, 68, 68, 0.32)' };
};

const getTrendDirection = (signal, indicators) => {
  const emaFast = getFirstNumeric(indicators, ['ema9', 'ema_9']);
  const emaSlow = getFirstNumeric(indicators, ['ema15', 'ema_15', 'ema21', 'ema_21']);

  if (Number.isFinite(emaFast) && Number.isFinite(emaSlow) && emaFast !== emaSlow) {
    return emaFast > emaSlow ? 'Bullish' : 'Bearish';
  }

  if (signal?.signal === 'BUY') return 'Bullish';
  if (signal?.signal === 'SELL') return 'Bearish';
  return 'Neutral';
};

const buildReasoning = (signal, indicators, trend) => {
  if (signal?.explanation && signal.explanation.trim()) return signal.explanation;

  const rsi = getFirstNumeric(indicators, ['rsi9', 'rsi_14', 'rsi']);
  const macd = getFirstNumeric(indicators, ['macd', 'macd_hist']);
  const rsiTone = !Number.isFinite(rsi) ? 'stable RSI' : rsi < 40 ? 'weak RSI pressure' : rsi > 60 ? 'strong RSI momentum' : 'balanced RSI';
  const macdTone = !Number.isFinite(macd) ? 'flat MACD' : macd >= 0 ? 'positive MACD crossover' : 'negative MACD crossover';

  return `${trend} structure detected with ${rsiTone} and ${macdTone}.`;
};

const buildSparklinePath = (values, width, height) => {
  if (!Array.isArray(values) || values.length < 2) return '';
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  return values
    .map((value, idx) => {
      const x = (idx / (values.length - 1)) * width;
      const y = height - ((value - min) / range) * height;
      return `${idx === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(' ');
};

const Sparkline = ({ candles, trend }) => {
  const values = useMemo(() => {
    return (candles || [])
      .slice(-24)
      .map((row) => Number(row?.close))
      .filter((num) => Number.isFinite(num));
  }, [candles]);

  if (values.length < 2) {
    return (
      <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontFamily: 'var(--font-family-mono)' }}>
        Trend preview unavailable
      </div>
    );
  }

  const chartWidth = 260;
  const chartHeight = 54;
  const stroke = trend === 'Bullish' ? '#22c55e' : trend === 'Bearish' ? '#ef4444' : '#94a3b8';
  const path = buildSparklinePath(values, chartWidth, chartHeight);

  return (
    <svg viewBox={`0 0 ${chartWidth} ${chartHeight + 4}`} width="100%" height="68" role="img" aria-label="Recent trend sparkline">
      <defs>
        <linearGradient id="sparklineGradient" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.35" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0.95" />
        </linearGradient>
      </defs>
      <path d={path} fill="none" stroke="url(#sparklineGradient)" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
};

const SignalCardInner = memo(({ signal, indicators, candles, isLoading, error, onRetry, onExecuteTrade, isExecuting }) => {
  if (isLoading || !signal) {
    return (
      <Card style={{ height: '100%', display: 'flex', justifyContent: 'center', alignItems: 'center', border: 'none', background: 'transparent' }}>
        <SkeletonCard height="100%" width="100%" />
      </Card>
    );
  }

  if (error) {
    return (
      <Card style={{ height: '100%', border: 'none', background: 'transparent' }}>
        <ErrorState title="Signal unavailable" message={error} onRetry={onRetry} />
      </Card>
    );
  }

  const confidence = Math.max(0, Math.min(100, Number(signal.confidence) || 0));
  const signalColor = signal.signal === 'BUY' ? '#22c55e' : signal.signal === 'SELL' ? '#ef4444' : '#f59e0b';
  const signalBg = signal.signal === 'BUY' ? 'rgba(34, 197, 94, 0.06)' : signal.signal === 'SELL' ? 'rgba(239, 68, 68, 0.06)' : 'rgba(245, 158, 11, 0.06)';
  const tradeStatus = getTradeStatus(confidence);
  const trend = getTrendDirection(signal, indicators);
  const reasoning = buildReasoning(signal, indicators, trend);

  const entry = Number(signal.currentPrice);
  const target = Number(signal.target);
  const stopLoss = Number(signal.stopLoss);
  const risk = Number.isFinite(entry) && Number.isFinite(stopLoss) ? Math.abs(entry - stopLoss) : null;
  const reward = Number.isFinite(entry) && Number.isFinite(target) ? Math.abs(target - entry) : null;
  const riskReward = Number.isFinite(risk) && Number.isFinite(reward) && risk > 0 ? (reward / risk) : null;

  const trendColor = trend === 'Bullish' ? '#22c55e' : trend === 'Bearish' ? '#ef4444' : '#94a3b8';

  return (
    <Card
      className="premium-signal-card"
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        fontFamily: 'var(--font-family-base)',
        background: `linear-gradient(165deg, ${signalBg} 0%, rgba(12, 17, 24, 0.95) 52%, rgba(6, 10, 14, 0.98) 100%)`,
        border: `1px solid ${signalColor}30`,
        padding: 'clamp(16px, 2.1vw, 24px)',
        overflowY: 'auto',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', marginBottom: '18px' }}>
        <h3 style={{ fontSize: '13px', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '1px', margin: 0 }}>
          {signal.symbol} AI Signal
        </h3>
        <span
          style={{
            fontSize: '10px',
            padding: '6px 10px',
            borderRadius: '999px',
            color: tradeStatus.color,
            background: tradeStatus.bg,
            border: `1px solid ${tradeStatus.border}`,
            fontFamily: 'var(--font-family-mono)',
            fontWeight: 700,
            letterSpacing: '0.5px',
            whiteSpace: 'nowrap',
          }}
        >
          {tradeStatus.label}
        </span>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: '12px', marginBottom: '16px', flexWrap: 'wrap' }}>
        <div style={{ fontSize: '48px', fontWeight: 800, color: signalColor, letterSpacing: '1.5px', lineHeight: 1 }}>
          {signal.signal}
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ color: 'var(--text-muted)', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.9px' }}>Confidence</div>
          <div style={{ color: '#fff', fontFamily: 'var(--font-family-mono)', fontSize: '32px', fontWeight: 800, lineHeight: 1.1 }}>{Math.round(confidence)}%</div>
        </div>
      </div>

      <div style={{ marginBottom: '18px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginBottom: '8px', color: 'var(--text-primary)' }}>
          <span style={{ color: 'var(--text-secondary)' }}>Model Confidence</span>
          <span style={{ color: signalColor, fontWeight: 700, fontFamily: 'var(--font-family-mono)' }}>{Math.round(confidence)}%</span>
        </div>
        <div style={{ width: '100%', height: '10px', background: 'rgba(255,255,255,0.08)', borderRadius: '999px', overflow: 'hidden', border: '1px solid var(--border-subtle, var(--border))' }}>
          <div
            style={{
              width: `${confidence}%`,
              height: '100%',
              borderRadius: '999px',
              background: signal.signal === 'SELL'
                ? 'linear-gradient(90deg, rgba(127, 29, 29, 0.95) 0%, rgba(239, 68, 68, 0.95) 55%, rgba(252, 165, 165, 0.95) 100%)'
                : 'linear-gradient(90deg, rgba(20, 184, 166, 0.95) 0%, rgba(52, 211, 153, 0.95) 55%, rgba(134, 239, 172, 0.95) 100%)',
              transition: 'width 0.85s cubic-bezier(0.22, 1, 0.36, 1)',
              backgroundSize: '220% 100%',
              animation: 'shimmer 2.4s linear infinite',
            }}
          />
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(112px, 1fr))', gap: '9px', marginBottom: '16px' }}>
        <div style={{ background: 'rgba(0, 0, 0, 0.28)', padding: '12px 10px', borderRadius: '10px', border: '1px solid var(--border-subtle, #1A2332)' }}>
          <div style={{ fontSize: '10px', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '8px', letterSpacing: '0.5px' }}>Entry</div>
          <div style={{ fontFamily: 'var(--font-family-mono)', fontWeight: 700, color: '#fff', fontSize: '14px' }}>{formatCurrency(entry)}</div>
        </div>
        <div style={{ background: 'rgba(0, 0, 0, 0.28)', padding: '12px 10px', borderRadius: '10px', border: '1px solid var(--border-subtle, #1A2332)' }}>
          <div style={{ fontSize: '10px', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '8px', letterSpacing: '0.5px' }}>Target</div>
          <div style={{ fontFamily: 'var(--font-family-mono)', fontWeight: 700, color: '#34d399', fontSize: '14px' }}>{formatCurrency(target)}</div>
        </div>
        <div style={{ background: 'rgba(0, 0, 0, 0.28)', padding: '12px 10px', borderRadius: '10px', border: '1px solid var(--border-subtle, #1A2332)' }}>
          <div style={{ fontSize: '10px', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '8px', letterSpacing: '0.5px' }}>Stop Loss</div>
          <div style={{ fontFamily: 'var(--font-family-mono)', fontWeight: 700, color: '#f87171', fontSize: '14px' }}>{formatCurrency(stopLoss)}</div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(146px, 1fr))', gap: '9px', marginBottom: '16px' }}>
        <div style={{ background: 'rgba(8, 12, 18, 0.72)', border: '1px solid var(--border-subtle, #1A2332)', borderRadius: '10px', padding: '11px 12px' }}>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px', letterSpacing: '0.5px' }}>Risk / Reward</div>
          <div style={{ fontFamily: 'var(--font-family-mono)', color: '#e2e8f0', fontWeight: 700, fontSize: '13px' }}>
            {Number.isFinite(riskReward) ? `1 : ${riskReward.toFixed(2)}` : 'NA'}
          </div>
        </div>
        <div style={{ background: 'rgba(8, 12, 18, 0.72)', border: '1px solid var(--border-subtle, #1A2332)', borderRadius: '10px', padding: '11px 12px' }}>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px', letterSpacing: '0.5px' }}>Trend Direction</div>
          <div style={{ fontFamily: 'var(--font-family-mono)', color: trendColor, fontWeight: 700, fontSize: '13px' }}>{trend}</div>
        </div>
      </div>

      <div style={{ background: 'rgba(5, 10, 14, 0.66)', border: '1px solid var(--border-subtle, #1A2332)', borderRadius: '10px', padding: '12px', marginBottom: '14px' }}>
        <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '8px', letterSpacing: '0.5px' }}>AI Reasoning</div>
        <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '12px', lineHeight: 1.45 }}>{reasoning}</p>
      </div>

      <div style={{ background: 'rgba(5, 10, 14, 0.6)', border: '1px solid var(--border-subtle, #1A2332)', borderRadius: '10px', padding: '10px 12px', marginBottom: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
          <span style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Recent Trend</span>
          <span style={{ fontSize: '11px', color: trendColor, fontFamily: 'var(--font-family-mono)', fontWeight: 700 }}>{trend}</span>
        </div>
        <Sparkline candles={candles} trend={trend} />
      </div>

      <button
        onClick={onExecuteTrade}
        disabled={isExecuting}
        style={{
          border: '1px solid rgba(0, 255, 159, 0.45)',
          background: 'linear-gradient(90deg, rgba(0, 255, 159, 0.12) 0%, rgba(0, 214, 255, 0.12) 100%)',
          color: '#dfffee',
          borderRadius: '10px',
          padding: '11px',
          cursor: isExecuting ? 'not-allowed' : 'pointer',
          fontWeight: 700,
          marginBottom: '14px',
          opacity: isExecuting ? 0.6 : 1,
          transition: 'filter 0.2s ease, transform 0.2s ease',
          fontFamily: 'var(--font-family-base)',
        }}
        onMouseEnter={(e) => {
          if (!isExecuting) {
            e.currentTarget.style.filter = 'brightness(1.08)';
            e.currentTarget.style.transform = 'translateY(-1px)';
          }
        }}
        onMouseLeave={(e) => {
          if (!isExecuting) {
            e.currentTarget.style.filter = 'brightness(1)';
            e.currentTarget.style.transform = 'translateY(0px)';
          }
        }}
      >
        {isExecuting ? 'Executing...' : `Simulate Trade (${signal.symbol})`}
      </button>

      <NewsPanel symbol={signal.symbol} />

      <div style={{ marginTop: 'auto', textAlign: 'right', fontSize: '11px', color: 'var(--text-secondary)' }}>
        Generated: {new Date(signal.timestamp).toLocaleTimeString('en-US', { timeZone: 'Asia/Kolkata' })} IST
      </div>
    </Card>
  );
});

export const SignalCard = () => {
  const {
    currentSignal,
    indicators,
    candles,
    isLoading,
    isSignalLoading,
    error,
    signalError,
    refreshBundle,
    refreshSignal,
    selectedSymbol,
  } = useAppContext();
  const { isAuthenticated } = useAuth();
  const { showToast } = useToast();
  const [isExecuting, setIsExecuting] = useState(false);

  const onExecuteTrade = async () => {
    if (!isAuthenticated) {
      showToast('Login required for trade simulation', 'warning');
      return;
    }

    setIsExecuting(true);
    try {
      const result = await api.executeTrade(selectedSymbol);
      const message = result?.message || (result?.executed ? 'Trade executed' : 'No execution');
      showToast(message, result?.executed ? 'success' : 'info');
    } catch (err) {
      showToast(err?.message || 'Trade simulation failed', 'error');
    } finally {
      setIsExecuting(false);
    }
  };

  return (
    <ErrorBoundary>
      <SignalCardInner
        signal={currentSignal}
        indicators={indicators}
        candles={candles}
        isLoading={isSignalLoading || (isLoading && !currentSignal)}
        error={signalError || (!currentSignal ? error : null)}
        onRetry={signalError ? refreshSignal : refreshBundle}
        onExecuteTrade={onExecuteTrade}
        isExecuting={isExecuting}
      />
    </ErrorBoundary>
  );
};

export default SignalCard;
