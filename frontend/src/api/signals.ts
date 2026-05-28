/**
 * Signals API Module
 */

import axiosInstance from './axios';
import { Signal, SignalFilters } from '../store/types';

export const signalsApi = {
  /**
   * Get signals with optional filters
   */
  getSignals: async (filters?: SignalFilters): Promise<Signal[]> => {
    const params: any = {};

    if (filters?.action) {
      params.action = filters.action;
    }
    if (filters?.confidence !== undefined) {
      params.confidence = filters.confidence;
    }
    if (filters?.timeframe) {
      params.timeframe = filters.timeframe;
    }
    if (filters?.symbol) {
      params.symbol = filters.symbol;
    }

    const response = await axiosInstance.get('/signals', { params });
    return response.data;
  },

  /**
   * Get signal history for a specific symbol
   */
  getSignalHistory: async (symbol: string): Promise<Signal[]> => {
    const response = await axiosInstance.get(`/signals/${symbol}/history`);
    return response.data;
  },
};
