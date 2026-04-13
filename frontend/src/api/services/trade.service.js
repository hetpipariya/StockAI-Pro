import { apiClient } from '../client.js';
import { API_ENDPOINTS } from '../endpoints.js';
export const TradeService = {
    execute: (signalId, symbol, type, size, tp, sl) => apiClient.post(API_ENDPOINTS.TRADES.EXECUTE, { signalId, symbol, type, size, tp, sl }),
    close: (tradeId) => apiClient.post(API_ENDPOINTS.TRADES.CLOSE(tradeId), { type: 'MARKET' }),
    getActive: () => apiClient.get(API_ENDPOINTS.TRADES.ACTIVE),
    getHistory: (page, limit) => apiClient.get(`${API_ENDPOINTS.TRADES.HISTORY}?page=${page}&limit=${limit}`)
};