/**
 * Portfolio API Module
 */

import axiosInstance from './axios';
import { Portfolio, Position } from '../store/types';

export const portfolioApi = {
  /**
   * Get user portfolio
   */
  getPortfolio: async (): Promise<Portfolio> => {
    const response = await axiosInstance.get('/portfolio');
    return response.data;
  },

  /**
   * Add a new position to portfolio
   */
  addPosition: async (
    symbol: string,
    quantity: number,
    entryPrice: number
  ): Promise<Position> => {
    const response = await axiosInstance.post('/portfolio', {
      symbol,
      quantity,
      entry_price: entryPrice,
    });
    return response.data;
  },

  /**
   * Update an existing position
   */
  updatePosition: async (
    id: string,
    quantity: number,
    entryPrice: number
  ): Promise<Position> => {
    const response = await axiosInstance.put(`/portfolio/${id}`, {
      quantity,
      entry_price: entryPrice,
    });
    return response.data;
  },

  /**
   * Delete a position from portfolio
   */
  deletePosition: async (id: string): Promise<void> => {
    await axiosInstance.delete(`/portfolio/${id}`);
  },
};
