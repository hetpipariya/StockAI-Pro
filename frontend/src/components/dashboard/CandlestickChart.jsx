import React, { memo, useEffect, useMemo, useRef, useState } from 'react';
import { createChart } from 'lightweight-charts';
import { motion } from 'framer-motion';
import { BarChart3 } from 'lucide-react';

const toChartTime = (value) => {
  if (typeof value === 'number') {
    if (value > 1_000_000_000_000) return Math.floor(value / 1000);
    return Math.floor(value);
  }

  if (typeof value === 'string') {
    const normalized = value.includes('T') ? value : `${value.replace(' ', 'T')}Z`;
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

  return normalized;
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
}) {
  const [showEma, setShowEma] = useState(true);
  const [showRsi, setShowRsi] = useState(true);
  const [showMacd, setShowMacd] = useState(false);

  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const ema20Ref = useRef(null);
  const ema50Ref = useRef(null);

  const normalizedCandles = useMemo(() => normalizeCandles(candles), [candles]);
  const ema20Series = useMemo(() => computeEmaSeries(normalizedCandles, 20), [normalizedCandles]);
  const ema50Series = useMemo(() => computeEmaSeries(normalizedCandles, 50), [normalizedCandles]);

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
      priceLineVisible: true,
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

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      ema20Ref.current = null;
      ema50Ref.current = null;
    };
  }, []);

  useEffect(() => {
    if (!candleSeriesRef.current || !ema20Ref.current || !ema50Ref.current) return;

    candleSeriesRef.current.setData(normalizedCandles);
    ema20Ref.current.setData(showEma ? ema20Series : []);
    ema50Ref.current.setData(showEma ? ema50Series : []);

    if (normalizedCandles.length > 0) {
      chartRef.current?.timeScale().fitContent();
    }
  }, [normalizedCandles, showEma, ema20Series, ema50Series, symbol, timeframe]);

  const rsi = toFiniteNumber(indicators?.rsi);
  const macdValue = toFiniteNumber(indicators?.macd?.value ?? indicators?.macd_value);
  const macdSignal = toFiniteNumber(indicators?.macd?.signal ?? indicators?.macd_signal);

  return (
    <div className="rounded-2xl border border-white/10 bg-[#080C12] hover:border-stockai-neon/40 transition-all duration-300 shadow-[0_0_0_rgba(0,255,159,0)] hover:shadow-[0_0_30px_rgba(0,255,159,0.08)]">
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
        <div className="flex items-center gap-3">
          <BarChart3 className="w-4 h-4 text-stockai-neon" />
          <p className="text-sm text-white font-semibold">{symbol} · {timeframe.toUpperCase()}</p>
        </div>
        <div className="flex items-center gap-2">
          <ToggleButton active={showEma} label="EMA" onClick={() => setShowEma((value) => !value)} />
          <ToggleButton active={showRsi} label="RSI" onClick={() => setShowRsi((value) => !value)} />
          <ToggleButton active={showMacd} label="MACD" onClick={() => setShowMacd((value) => !value)} />
        </div>
      </div>

      {(showRsi || showMacd) && (
        <div className="px-4 py-2 border-b border-white/5 flex items-center gap-4 text-xs text-stockai-muted">
          {showRsi && <span>RSI: {rsi === null ? '--' : rsi.toFixed(2)}</span>}
          {showMacd && <span>MACD: {macdValue === null ? '--' : macdValue.toFixed(2)} / {macdSignal === null ? '--' : macdSignal.toFixed(2)}</span>}
        </div>
      )}

      <div className="relative h-[420px]">
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.28 }}
          ref={containerRef}
          className={`absolute inset-0 transition-opacity duration-300 ${
            !isLoading && normalizedCandles.length > 0 ? 'opacity-100' : 'opacity-0'
          }`}
        />

        {isLoading && (
          <div className="absolute inset-0 p-4">
            <div className="h-full w-full rounded-xl bg-gradient-to-r from-white/5 via-white/10 to-white/5 animate-pulse" />
          </div>
        )}

        {!isLoading && normalizedCandles.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-stockai-muted">
            Chart data unavailable for this symbol/timeframe.
          </div>
        )}
      </div>
    </div>
  );
});

export default CandlestickChart;
