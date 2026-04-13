import { apiClient } from '../client.js';
import { API_ENDPOINTS } from '../endpoints.js';
export const PortfolioService = {
    getBalance: () => apiClient.get(API_ENDPOINTS.PORTFOLIO.BALANCE),
    getHistory: (timeframe = '1D') => apiClient.get(`${API_ENDPOINTS.PORTFOLIO.HISTORY}?timeframe=${timeframe}`)
};