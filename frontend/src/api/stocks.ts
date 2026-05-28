/**
 * Stocks API Module
 */

import axiosInstance from './axios';
import { Stock, OHLCV, MarketStatus } from '../store/types';

export const stocksApi = {
  /**
   * Search stocks by query
   */
  searchStocks: async (query: string): Promise<Stock[]> => {
    const response = await axiosInstance.get('/stocks/search', {
      params: { q: query },
    });
    return response.data;
  },

  /**
   * Get stock quote with current price
   */
  getQuote: async (symbol: string): Promise<Stock> => {
    const response = await axiosInstance.get(`/stocks/${symbol}/quote`);
    return response.data;
  },

  /**
   * Get historical OHLCV data
   */
  getHistory: async (
    symbol: string,
    timeframe: string = '1d',
    limit: number = 100
  ): Promise<OHLCV[]> => {
    const response = await axiosInstance.get(`/stocks/${symbol}/history`, {
      params: {
        tf: timeframe,
        limit,
      },
    });
    return response.data;
  },

  /**
   * Get market status and indices
   */
  getMarketStatus: async (): Promise<MarketStatus> => {
    const response = await axiosInstance.get('/market/status');
    return response.data;
  },
};
