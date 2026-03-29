import React, { useEffect, useRef, useMemo } from 'react';
import { createChart } from 'lightweight-charts';
import { Button } from '../ui/Button';
import { useAppContext } from '../../context/AppContext';
import ErrorBoundary from '../ErrorBoundary';
import { SkeletonCard } from '../ui/Skeleton';
import ErrorState from '../ui/ErrorState';

const TIMEFRAMES = ['1m', '5m', '15m', '30m', '1h', '1d'];

const getFirstNumericIndicator = (source, keys) => {
  for (const key of keys) {
    const value = Number(source?.[key]);
    if (Number.isFinite(value)) return value;
  }
  return null;
};

const formatValue = (value, digits = 2) => {
  if (!Number.isFinite(value)) return '--';
  return Number(value).toLocaleString('en-IN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
};

const ChartPanelInner = ({ hideHeader = false, chartPadding = '14px' }) => {
  const {
    selectedSymbol,
    selectedTimeframe,
    selectTimeframe,
    candles,
    indicators,
    isLoading,
    error,
    refreshBundle,
  } = useAppContext();
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);

  // Memoize stable array to avoid GC and redrawing churn
  const stableCandles = useMemo(() => candles || [], [candles]);

  const indicatorSummary = useMemo(() => {
    return {
      ema: getFirstNumericIndicator(indicators, ['ema9', 'ema_9', 'ema15', 'ema']),
      rsi: getFirstNumericIndicator(indicators, ['rsi9', 'rsi_14', 'rsi']),
      macd: getFirstNumericIndicator(indicators, ['macd', 'macd_hist']),
    };
  }, [indicators]);

  const indicatorBadges = useMemo(() => {
    const rsiTone = !Number.isFinite(indicatorSummary.rsi)
      ? { bg: 'rgba(148, 163, 184, 0.1)', border: 'rgba(148, 163, 184, 0.3)', text: '#cbd5e1' }
      : indicatorSummary.rsi > 60
        ? { bg: 'rgba(34, 197, 94, 0.14)', border: 'rgba(34, 197, 94, 0.35)', text: '#4ade80' }
        : indicatorSummary.rsi < 40
          ? { bg: 'rgba(239, 68, 68, 0.14)', border: 'rgba(239, 68, 68, 0.35)', text: '#f87171' }
          : { bg: 'rgba(148, 163, 184, 0.12)', border: 'rgba(148, 163, 184, 0.3)', text: '#cbd5e1' };

    const macdTone = !Number.isFinite(indicatorSummary.macd)
      ? { bg: 'rgba(148, 163, 184, 0.1)', border: 'rgba(148, 163, 184, 0.25)', text: '#cbd5e1' }
      : indicatorSummary.macd >= 0
        ? { bg: 'rgba(34, 197, 94, 0.11)', border: 'rgba(34, 197, 94, 0.32)', text: '#4ade80' }
        : { bg: 'rgba(239, 68, 68, 0.12)', border: 'rgba(239, 68, 68, 0.32)', text: '#fca5a5' };

    return [
      {
        key: 'ema',
        label: 'EMA',
        value: formatValue(indicatorSummary.ema, 2),
        bg: 'rgba(56, 189, 248, 0.12)',
        border: 'rgba(56, 189, 248, 0.35)',
        text: '#7dd3fc',
      },
      {
        key: 'rsi',
        label: 'RSI',
        value: formatValue(indicatorSummary.rsi, 1),
        ...rsiTone,
      },
      {
        key: 'macd',
        label: 'MACD',
        value: formatValue(indicatorSummary.macd, 2),
        ...macdTone,
      },
    ];
  }, [indicatorSummary]);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: 'solid', color: 'transparent' },
        textColor: '#a1a1aa',
      },
      grid: {
        vertLines: { color: '#1A2332' },
        horzLines: { color: '#1A2332' },
      },
      width: chartContainerRef.current.clientWidth,
      height: chartContainerRef.current.clientHeight,
      timeScale: {
        borderColor: '#1A2332',
        timeVisible: true,
      },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: '#00FF9F',
      downColor: '#FF4C4C',
      borderDownColor: '#FF4C4C',
      borderUpColor: '#00FF9F',
      wickDownColor: '#FF4C4C',
      wickUpColor: '#00FF9F',
    });

    chartRef.current = chart;
    seriesRef.current = candleSeries;

    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight,
        });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      if (chartRef.current) chartRef.current.remove();
    };
  }, []);

  useEffect(() => {
    if (seriesRef.current && chartRef.current && stableCandles.length > 0) {
      seriesRef.current.setData(stableCandles);
      chartRef.current.timeScale().fitContent();
    }
  }, [stableCandles]);

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'transparent' }}>
      {!hideHeader && (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', borderBottom: '1px solid var(--border-subtle, var(--border))', gap: '12px', flexWrap: 'wrap' }}>
          <h2 style={{ margin: 0, fontSize: '18px', display: 'flex', alignItems: 'center', gap: '8px', color: '#fff', fontFamily: 'var(--font-family-base)' }}>
            {selectedSymbol}
            <span style={{ fontSize: '12px', color: 'var(--text-secondary)', fontWeight: 'normal' }}>NSE</span>
          </h2>

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '10px', flexWrap: 'wrap', marginLeft: 'auto' }}>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              {TIMEFRAMES.map(tf => (
                <div key={tf} style={{ zoom: 0.8 }} className="touch-target">
                  <Button
                    label={tf.toUpperCase()}
                    variant={selectedTimeframe === tf ? 'primary' : 'ghost'}
                    onClick={() => selectTimeframe(tf)}
                  />
                </div>
              ))}
            </div>

            <div
              aria-hidden="true"
              style={{ width: '1px', alignSelf: 'stretch', minHeight: '24px', background: 'var(--border-subtle, var(--border))' }}
            />

            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              {indicatorBadges.map((badge) => (
                <div
                  key={badge.key}
                  className="indicator-pill"
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    borderRadius: '999px',
                    padding: '6px 10px',
                    background: badge.bg,
                    border: `1px solid ${badge.border}`,
                    fontFamily: 'var(--font-family-mono)',
                    fontSize: '11px',
                    whiteSpace: 'nowrap',
                    transition: 'transform 0.2s ease, filter 0.2s ease, border-color 0.2s ease',
                  }}
                >
                  <span style={{ color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.35px' }}>{badge.label}:</span>
                  <span style={{ color: badge.text, fontWeight: 700 }}>{badge.value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Chart Wrapper */}
      <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
        {isLoading ? (
          <div style={{ padding: chartPadding }}>
            <SkeletonCard width="100%" height="360px" />
          </div>
        ) : error ? (
          <div style={{ padding: chartPadding }}>
            <ErrorState title="Unable to load chart" message={error} onRetry={refreshBundle} />
          </div>
        ) : (
          <>
            <div ref={chartContainerRef} style={{ width: '100%', height: '100%' }} />
          </>
        )}
      </div>
    </div>
  );
};

export const ChartPanel = (props) => (
  <ErrorBoundary>
    <ChartPanelInner {...props} />
  </ErrorBoundary>
);

export default ChartPanel;
