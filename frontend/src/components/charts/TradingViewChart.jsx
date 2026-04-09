/**
 * TradingView Chart Wrapper Component
 * Premium charting component using lightweight-charts.
 * Custom dark theme, responsive, with volume histogram, crosshair, and smooth scrolling.
 */

import React, { useEffect, useRef, useState } from 'react';
import { createChart, ColorType } from 'lightweight-charts';
import { motion } from 'framer-motion';
import { TrendingUp } from 'lucide-react';

/**
 * Custom dark theme configuration
 */
const CHART_THEME = {
  layout: {
    background: { type: ColorType.Solid, color: '#0f172a' }, // slate-900
    textColor: '#cbd5e1', // slate-300
    attributionLogo: false,
  },
  grid: {
    vertLines: { color: 'rgba(203, 213, 225, 0.05)' },
    horzLines: { color: 'rgba(203, 213, 225, 0.05)' },
  },
  timeScale: {
    borderColor: 'rgba(3, 102, 214, 0.2)',
    timeVisible: true,
    secondsVisible: false,
    shiftVisibleRangeOnNewBar: true,
  },
  crosshair: {
    mode: 1, // Magnet mode
    vertLine: {
      color: 'rgba(59, 130, 246, 0.5)',
      width: 1,
      style: 2, // Dashed
    },
    horzLine: {
      color: 'rgba(59, 130, 246, 0.5)',
      width: 1,
      style: 2,
    },
  },
};

/**
 * Candlestick colors
 */
const CANDLE_COLORS = {
  upColor: '#00ff9f', // Matrix green
  downColor: '#ff4c4c', // Warning red
  borderUpColor: '#00ff9f',
  borderDownColor: '#ff4c4c',
  wickUpColor: '#00ff9f',
  wickDownColor: '#ff4c4c',
};

/**
 * Volume histogram colors
 */
const VOLUME_COLORS = {
  upColor: 'rgba(0, 255, 159, 0.4)',
  downColor: 'rgba(255, 76, 76, 0.4)',
};

/**
 * TradingView Chart Wrapper Component
 * @component
 * @param {Object} props - Component props
 * @param {Array} props.candles - OHLCV candles data
 * @param {string} props.symbol - Stock symbol
 * @param {string} props.interval - Time interval ('1m', '5m', etc)
 */
export function TradingViewChart({ candles = [], symbol = 'RELIANCE', interval = '1m' }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const volumeSeriesRef = useRef(null);
  const [isLoading, setIsLoading] = useState(true);
  const [priceInfo, setPriceInfo] = useState(null);

  /**
   * Initialize chart on mount and data change
   */
  useEffect(() => {
    if (!containerRef.current || !candles.length) return;

    setIsLoading(true);

    try {
      // Clean up existing chart
      if (chartRef.current) {
        chartRef.current.remove();
      }

      // Create new chart instance
      const chart = createChart(containerRef.current, {
        ...CHART_THEME,
        width: containerRef.current.clientWidth,
        height: containerRef.current.clientHeight,
        timeScale: {
          ...CHART_THEME.timeScale,
        },
      });

      // Add candlestick series
      const candleSeries = chart.addCandlestickSeries({
        ...CANDLE_COLORS,
        upColor: CANDLE_COLORS.upColor,
        downColor: CANDLE_COLORS.downColor,
      });

      // Add volume histogram series
      const volumeSeries = chart.addHistogramSeries({
        color: 'rgba(0, 255, 159, 0.2)',
        priceFormat: {
          type: 'volume',
        },
        priceScaleId: 'right',
      });

      // Set data
      candleSeries.setData(
        candles.map((candle) => ({
          time: candle.time,
          open: candle.open,
          high: candle.high,
          low: candle.low,
          close: candle.close,
        }))
      );

      volumeSeries.setData(
        candles.map((candle) => ({
          time: candle.time,
          value: candle.volume,
          color:
            candle.close >= candle.open
              ? VOLUME_COLORS.upColor
              : VOLUME_COLORS.downColor,
        }))
      );

      // Scale prices
      chart.priceScale('right').applyOptions({ mode: 1 }); // Percentage mode
      chart.priceScale('left').applyOptions({
        autoScale: true,
        mode: 0, // Normal mode
      });

      // Time scale setup
      const timeScale = chart.timeScale();
      timeScale.fitContent();
      timeScale.applyOptions({
        barSpacing: 8,
      });

      // Store references
      chartRef.current = chart;
      candleSeriesRef.current = candleSeries;
      volumeSeriesRef.current = volumeSeries;

      // Update price info from latest candle
      if (candles.length > 0) {
        const latest = candles[candles.length - 1];
        const previous = candles.length > 1 ? candles[candles.length - 2] : latest;
        const change = latest.close - previous.close;
        const changePercent = (change / previous.close) * 100;

        setPriceInfo({
          close: latest.close,
          change,
          changePercent,
          high: latest.high,
          low: latest.low,
          volume: latest.volume,
        });
      }

      setIsLoading(false);

      // Handle resize
      const handleResize = () => {
        if (containerRef.current && chartRef.current) {
          setTimeout(() => {
            chartRef.current.applyOptions({
              width: containerRef.current.clientWidth,
              height: containerRef.current.clientHeight,
            });
          }, 100);
        }
      };

      window.addEventListener('resize', handleResize);

      return () => {
        window.removeEventListener('resize', handleResize);
        if (chartRef.current) {
          chartRef.current.remove();
          chartRef.current = null;
        }
      };
    } catch (error) {
      console.error('Chart initialization error:', error);
      setIsLoading(false);
    }
  }, [candles]);

  // Format currency
  const formatPrice = (value) => {
    return `₹${value.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5 }}
      className="w-full h-full flex flex-col bg-slate-900 rounded-xl overflow-hidden border border-blue-500/10"
    >
      {/* Chart Header */}
      <div className="px-6 py-4 border-b border-blue-500/10 flex items-center justify-between bg-gradient-to-r from-slate-900 to-slate-800/50">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp size={20} className="text-blue-400" />
            <h3 className="text-lg font-semibold text-white">{symbol}</h3>
            <span className="text-xs px-2 py-1 rounded bg-slate-700/50 text-slate-300">
              {interval.toUpperCase()}
            </span>
          </div>
          {priceInfo && (
            <div className="flex items-baseline gap-3">
              <span className="text-2xl font-bold text-white">
                {formatPrice(priceInfo.close)}
              </span>
              <span
                className={`text-sm font-medium ${
                  priceInfo.change >= 0 ? 'text-green-400' : 'text-red-400'
                }`}
              >
                {priceInfo.change >= 0 ? '+' : ''}
                {priceInfo.change.toFixed(2)} ({priceInfo.changePercent.toFixed(2)}%)
              </span>
            </div>
          )}
        </div>

        {/* Stats */}
        {priceInfo && (
          <div className="grid grid-cols-3 gap-4 text-right">
            <div>
              <p className="text-xs text-slate-400 mb-1">HIGH</p>
              <p className="text-sm font-semibold text-white">
                {formatPrice(priceInfo.high)}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-400 mb-1">LOW</p>
              <p className="text-sm font-semibold text-white">
                {formatPrice(priceInfo.low)}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-400 mb-1">VOL</p>
              <p className="text-sm font-semibold text-white">
                {(priceInfo.volume / 1000000).toFixed(1)}M
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Chart Container */}
      <div className="flex-1 relative overflow-hidden">
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm z-10">
            <div className="text-center">
              <div className="w-8 h-8 border-2 border-blue-400/30 border-t-blue-400 rounded-full animate-spin mx-auto mb-3" />
              <p className="text-slate-400">Loading chart...</p>
            </div>
          </div>
        )}
        <div ref={containerRef} className="w-full h-full" />
      </div>

      {/* Footer Info */}
      <div className="px-6 py-3 border-t border-blue-500/10 bg-slate-900/50 text-xs text-slate-400 flex gap-3">
        <span>🖱️ Pan: Drag horizontally</span>
        <span>🔍 Zoom: Scroll wheel</span>
        <span>✨ Crosshair: Hover</span>
      </div>
    </motion.div>
  );
}

export default TradingViewChart;
