/**
 * Watchlist API Module
 */

import axiosInstance from './axios';
import { Stock, WatchlistItem } from '../store/types';

export const watchlistApi = {
  /**
   * Get user watchlist
   */
  getWatchlist: async (): Promise<Stock[]> => {
    const response = await axiosInstance.get('/watchlist');
    return response.data;
  },

  /**
   * Add stock to watchlist
   */
  addToWatchlist: async (symbol: string): Promise<WatchlistItem> => {
    const response = await axiosInstance.post('/watchlist', { symbol });
    return response.data;
  },

  /**
   * Remove stock from watchlist
   */
  removeFromWatchlist: async (symbol: string): Promise<void> => {
    await axiosInstance.delete(`/watchlist/${symbol}`);
  },
};
