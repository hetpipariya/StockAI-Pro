import { apiClient } from '../client.js';
import { API_ENDPOINTS } from '../endpoints.js';

const toNumber = (value, fallback = null) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
};

export const TradeService = {
    execute: async (signalId, symbol) => {
        const normalizedSymbol = String(symbol || '').trim().toUpperCase();
        if (!normalizedSymbol) {
            throw new Error('Symbol is required for trade execution');
        }

        const payload = await apiClient.post(API_ENDPOINTS.TRADES.EXECUTE, null, {
            params: { symbol: normalizedSymbol },
        });

        if (!payload?.executed) {
            throw new Error(payload?.message || 'Trade execution blocked');
        }

        const executedPrice = toNumber(
            payload?.executedPrice
            ?? payload?.entry_price
            ?? payload?.entry
            ?? payload?.price,
            null,
        );

        return {
            tradeId: payload?.tradeId || payload?.order_id || `${normalizedSymbol}-${Date.now()}`,
            executedPrice,
            raw: payload,
        };
    },
    close: (tradeId) => apiClient.post(API_ENDPOINTS.TRADES.CLOSE(tradeId), { type: 'MARKET' }),
    getActive: () => apiClient.get(API_ENDPOINTS.TRADES.ACTIVE),
    /** Trade journal from DB — GET /api/v1/trading/journal */
    getJournal: (limit = 100) =>
        apiClient.get(`${API_ENDPOINTS.TRADING.JOURNAL}?limit=${encodeURIComponent(limit)}`),
};