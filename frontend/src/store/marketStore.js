/**
 * Market Data Store - Zustand
 * Global state for selected symbol, watchlist, and real-time market data.
 * Optimized for minimal re-renders with subscribed components only.
 */

import { create } from 'zustand';

/**
 * Market Data Store
 * @typedef {Object} MarketState
 * @property {string} selectedSymbol - Currently selected stock symbol
 * @property {Array} watchlist - Watched symbols list
 * @property {Object} latestPrice - Real-time price data
 * @property {Function} setSelectedSymbol - Update selected symbol
 * @property {Function} addToWatchlist - Add symbol to watchlist
 * @property {Function} removeFromWatchlist - Remove symbol from watchlist
 * @property {Function} updateLatestPrice - Update real-time price
 */
export const useMarketStore = create((set) => ({
  selectedSymbol: 'RELIANCE',
  watchlist: ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK'],
  latestPrice: {},

  setSelectedSymbol: (symbol) => {
    set({ selectedSymbol: symbol });
  },

  addToWatchlist: (symbol) => {
    set((state) => ({
      watchlist: Array.from(new Set([...state.watchlist, symbol])),
    }));
  },

  removeFromWatchlist: (symbol) => {
    set((state) => ({
      watchlist: state.watchlist.filter((s) => s !== symbol),
    }));
  },

  updateLatestPrice: (symbol, priceData) => {
    set((state) => ({
      latestPrice: {
        ...state.latestPrice,
        [symbol]: priceData,
      },
    }));
  },
}));

export default useMarketStore;
