import React, { memo, useEffect, useMemo, useRef, useState } from 'react';
import { createChart } from 'lightweight-charts';
import { motion } from 'framer-motion';
import { BarChart3 } from 'lucide-react';

const normalizeTimestampString = (value) => {
  const raw = String(value || '').trim();
  if (!raw) return '';
  if (raw.includes('T')) return raw;

  const normalized = raw.replace(' ', 'T');
  if (/[zZ]$/.test(normalized) || /[+-]\d{2}:\d{2}$/.test(normalized)) {
    return normalized;
  }

  return `${normalized}Z`;
};

const toChartTime = (value) => {
  if (typeof value === 'number') {
    if (value > 1_000_000_000_000) return Math.floor(value / 1000);
    return Math.floor(value);
  }

  if (typeof value === 'string') {
    const normalized = normalizeTimestampString(value);
    const millis = Date.parse(normalized);
    if (Number.isFinite(millis)) return Math.floor(millis / 1000);
  }

  return null;
};

const toFiniteNumber = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const normalizeCandles = (candles) => {
  if (!Array.isArray(candles)) return [];

  const normalized = candles
    .map((candle) => {
      const time = toChartTime(candle.time);
      const open = toFiniteNumber(candle.open);
      const high = toFiniteNumber(candle.high);
      const low = toFiniteNumber(candle.low);
      const close = toFiniteNumber(candle.close);

      if (time === null || open === null || high === null || low === null || close === null) {
        return null;
      }

      return {
        time,
        open,
        high,
        low,
        close,
      };
    })
    .filter(Boolean)
    .sort((left, right) => left.time - right.time);

  // Lightweight Charts requires strictly increasing unique timestamps.
  // Keep the latest candle for duplicate timestamps to avoid runtime rendering errors.
  const deduped = new Map();
  normalized.forEach((candle) => {
    deduped.set(candle.time, candle);
  });

  return Array.from(deduped.values()).sort((left, right) => left.time - right.time);
};

const computeEmaSeries = (candles, period) => {
  if (!candles.length) return [];

  const multiplier = 2 / (period + 1);
  let previousEma = candles[0].close;

  return candles.map((candle, index) => {
    previousEma = index === 0
      ? candles[0].close
      : (candle.close - previousEma) * multiplier + previousEma;

    return {
      time: candle.time,
      value: Number(previousEma.toFixed(2)),
    };
  });
};

const ToggleButton = ({ active, label, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    className={`px-2.5 py-1 rounded-lg text-xs border transition-all ${
      active
        ? 'border-stockai-neon/60 text-stockai-neon bg-stockai-neon/10'
        : 'border-white/10 text-stockai-muted hover:border-white/25 hover:text-white'
    }`}
  >
    {label}
  </button>
);

const CandlestickChart = memo(function CandlestickChart({
  candles,
  symbol,
  timeframe,
  isLoading,
  indicators,
  livePrice,
  tradeLevels,
  signalType,
}) {
  const [showEma, setShowEma] = useState(true);
  const [showRsi, setShowRsi] = useState(true);
  const [showMacd, setShowMacd] = useState(false);
  const [chartError, setChartError] = useState(null);

  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const ema20Ref = useRef(null);
  const ema50Ref = useRef(null);
  const livePriceLineRef = useRef(null);
  const entryLineRef = useRef(null);
  const stopLineRef = useRef(null);
  const targetLineRef = useRef(null);
  const hasManualZoomRef = useRef(false);

  const normalizedCandles = useMemo(() => normalizeCandles(candles), [candles]);
  const ema20Series = useMemo(() => computeEmaSeries(normalizedCandles, 20), [normalizedCandles]);
  const ema50Series = useMemo(() => computeEmaSeries(normalizedCandles, 50), [normalizedCandles]);
  const safeSymbol = useMemo(() => String(symbol || 'SYMBOL').toUpperCase(), [symbol]);
  const safeTimeframe = useMemo(() => String(timeframe || '--').toUpperCase(), [timeframe]);
  const normalizedLivePrice = useMemo(() => {
    const parsed = toFiniteNumber(livePrice);
    return parsed !== null && parsed > 0 ? parsed : null;
  }, [livePrice]);

  useEffect(() => {
    hasManualZoomRef.current = false;
  }, [safeSymbol, safeTimeframe]);

  useEffect(() => {
    if (!containerRef.current || chartRef.current) return undefined;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: '#070B12' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.04)' },
        horzLines: { color: 'rgba(255,255,255,0.04)' },
      },
      crosshair: {
        vertLine: {
          color: 'rgba(0,255,159,0.45)',
          width: 1,
          style: 2,
        },
        horzLine: {
          color: 'rgba(0,255,159,0.28)',
          width: 1,
          style: 2,
        },
      },
      timeScale: {
        borderColor: 'rgba(255,255,255,0.1)',
        timeVisible: true,
      },
      rightPriceScale: {
        borderColor: 'rgba(255,255,255,0.1)',
      },
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
      autoSize: true,
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: '#00FF9F',
      downColor: '#FF3366',
      borderVisible: false,
      wickUpColor: '#00FF9F',
      wickDownColor: '#FF3366',
      priceLineVisible: false,
    });

    const ema20 = chart.addLineSeries({
      color: '#22d3ee',
      lineWidth: 1.5,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    const ema50 = chart.addLineSeries({
      color: '#f59e0b',
      lineWidth: 1.5,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    ema20Ref.current = ema20;
    ema50Ref.current = ema50;

    const resizeObserver = new ResizeObserver(() => {
      if (!containerRef.current || !chartRef.current) return;
      chartRef.current.applyOptions({
        width: containerRef.current.clientWidth,
        height: containerRef.current.clientHeight,
      });
    });

    resizeObserver.observe(containerRef.current);

    const markManualZoom = () => {
      hasManualZoomRef.current = true;
    };

    containerRef.current.addEventListener('wheel', markManualZoom, { passive: true });
    containerRef.current.addEventListener('pointerdown', markManualZoom);
    containerRef.current.addEventListener('touchstart', markManualZoom, { passive: true });

    return () => {
      resizeObserver.disconnect();
      containerRef.current?.removeEventListener('wheel', markManualZoom);
      containerRef.current?.removeEventListener('pointerdown', markManualZoom);
      containerRef.current?.removeEventListener('touchstart', markManualZoom);
      if (candleSeriesRef.current && livePriceLineRef.current) {
        candleSeriesRef.current.removePriceLine(livePriceLineRef.current);
      }
      if (candleSeriesRef.current && entryLineRef.current) candleSeriesRef.current.removePriceLine(entryLineRef.current);
      if (candleSeriesRef.current && stopLineRef.current) candleSeriesRef.current.removePriceLine(stopLineRef.current);
      if (candleSeriesRef.current && targetLineRef.current) candleSeriesRef.current.removePriceLine(targetLineRef.current);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      ema20Ref.current = null;
      ema50Ref.current = null;
      livePriceLineRef.current = null;
      entryLineRef.current = null;
      stopLineRef.current = null;
      targetLineRef.current = null;
    };
  }, []);

  const latestLivePriceRef = useRef(normalizedLivePrice);
  const latestCandlesRef = useRef(normalizedCandles);
  const ema20SeriesRef = useRef(ema20Series);
  const ema50SeriesRef = useRef(ema50Series);

  const candlesDirtyRef = useRef(false);
  const priceDirtyRef = useRef(false);

  useEffect(() => {
    latestLivePriceRef.current = normalizedLivePrice;
    priceDirtyRef.current = true;
  }, [normalizedLivePrice]);

  useEffect(() => {
    latestCandlesRef.current = normalizedCandles;
    ema20SeriesRef.current = ema20Series;
    ema50SeriesRef.current = ema50Series;
    candlesDirtyRef.current = true;
  }, [normalizedCandles, ema20Series, ema50Series]);

  useEffect(() => {
    let animationFrameId;
    let lastUpdateMs = 0;
    const UPDATE_INTERVAL_MS = 60; // Max ~16 FPS visual chart refresh boundary is completely smooth but saves massive CPU

    const flushUpdates = () => {
      const now = Date.now();
      if (now - lastUpdateMs >= UPDATE_INTERVAL_MS) {
        lastUpdateMs = now;

        // 1. Flush candles if dirty
        if (candlesDirtyRef.current && candleSeriesRef.current && latestCandlesRef.current) {
          try {
            candleSeriesRef.current.setData(latestCandlesRef.current);
            ema20Ref.current?.setData(showEma ? ema20SeriesRef.current : []);
            ema50Ref.current?.setData(showEma ? ema50SeriesRef.current : []);
            candlesDirtyRef.current = false;
            setChartError(null);

            if (latestCandlesRef.current.length > 0 && !hasManualZoomRef.current) {
              chartRef.current?.timeScale().fitContent();
            }
          } catch (error) {
            setChartError('Chart rendering failed for current candle set. Waiting for next update.');
            candleSeriesRef.current?.setData([]);
            ema20Ref.current?.setData([]);
            ema50Ref.current?.setData([]);
          }
        }

        // 2. Flush live price line if dirty
        if (priceDirtyRef.current && candleSeriesRef.current) {
          const price = latestLivePriceRef.current;
          try {
            if (price === null) {
              if (livePriceLineRef.current) {
                candleSeriesRef.current.removePriceLine(livePriceLineRef.current);
                livePriceLineRef.current = null;
              }
            } else {
              if (!livePriceLineRef.current) {
                livePriceLineRef.current = candleSeriesRef.current.createPriceLine({
                  price: price,
                  color: '#38bdf8',
                  lineWidth: 1.5,
                  lineStyle: 2,
                  axisLabelVisible: true,
                  title: 'LIVE',
                });
              } else {
                livePriceLineRef.current.applyOptions({ price });
              }
            }
            priceDirtyRef.current = false;
          } catch (error) {
            // silent catch
          }
        }
      }
      animationFrameId = requestAnimationFrame(flushUpdates);
    };

    animationFrameId = requestAnimationFrame(flushUpdates);
    return () => cancelAnimationFrame(animationFrameId);
  }, [showEma]);

  useEffect(() => {
    if (!candleSeriesRef.current) return;

    try {
      const entry = toFiniteNumber(tradeLevels?.entry);
      const stop = toFiniteNumber(tradeLevels?.stopLoss);
      const target = toFiniteNumber(tradeLevels?.target);

      if (entryLineRef.current) candleSeriesRef.current.removePriceLine(entryLineRef.current);
      if (stopLineRef.current) candleSeriesRef.current.removePriceLine(stopLineRef.current);
      if (targetLineRef.current) candleSeriesRef.current.removePriceLine(targetLineRef.current);
      entryLineRef.current = null;
      stopLineRef.current = null;
      targetLineRef.current = null;

      if (entry !== null && entry > 0) {
        entryLineRef.current = candleSeriesRef.current.createPriceLine({ price: entry, color: '#00ff9f', lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: 'ENTRY' });
      }
      if (stop !== null && stop > 0) {
        stopLineRef.current = candleSeriesRef.current.createPriceLine({ price: stop, color: '#ff4d4f', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'SL' });
      }
      if (target !== null && target > 0) {
        targetLineRef.current = candleSeriesRef.current.createPriceLine({ price: target, color: '#22c55e', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'TGT' });
      }
    } catch (error) {
      if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.error('[CandlestickChart] trade level update failed', error);
      }
    }
  }, [tradeLevels]);

  const rsi = toFiniteNumber(indicators?.rsi);
  const macdValue = toFiniteNumber(indicators?.macd?.value ?? indicators?.macd_value);
  const macdSignal = toFiniteNumber(indicators?.macd?.signal ?? indicators?.macd_signal);

  return (
    <div className="w-full h-full flex flex-col bg-[#050816] border border-white/5 rounded-xl overflow-hidden hover:border-[#00F5FF]/35 transition-all duration-300 shadow-[0_0_30px_rgba(0,245,255,0.02)]">
      
      {/* Top indicator stats */}
      {(showRsi || showMacd) && (
        <div className="px-4 py-1.5 border-b border-white/5 flex flex-wrap items-center gap-4 text-[10px] text-slate-500 font-mono select-none">
          {showRsi && <span>RSI: <strong className="text-amber-400">{rsi === null ? '--' : rsi.toFixed(2)}</strong></span>}
          {showMacd && <span>MACD: <strong className="text-cyan-300">{macdValue === null ? '--' : macdValue.toFixed(2)} / {macdSignal === null ? '--' : macdSignal.toFixed(2)}</strong></span>}
        </div>
      )}

      {/* Main Chart container */}
      <div className="flex-1 relative w-full min-h-[300px]">
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.28 }}
          ref={containerRef}
          className={`absolute inset-0 transition-opacity duration-300 ${
            !isLoading && !chartError && normalizedCandles.length > 0 ? 'opacity-100' : 'opacity-0'
          }`}
        />

        {isLoading && (
          <div className="absolute inset-0 p-4">
            <div className="h-full w-full rounded-xl bg-gradient-to-r from-white/5 via-white/10 to-white/5 animate-pulse" />
          </div>
        )}

        {!isLoading && chartError && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-rose-300 px-4 text-center">
            {chartError}
          </div>
        )}

        {!isLoading && !chartError && normalizedCandles.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center text-xs text-slate-600 font-mono uppercase tracking-widest">
            Chart data unavailable for this symbol/timeframe.
          </div>
        )}
      </div>

    </div>
  );
});

export default CandlestickChart;
