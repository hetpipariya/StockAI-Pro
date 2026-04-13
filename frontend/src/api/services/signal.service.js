import { apiClient } from '../client.js';
import { API_ENDPOINTS } from '../endpoints.js';
export const SignalService = {
    getActive: (limit = 50) => apiClient.get(`${API_ENDPOINTS.SIGNALS.ACTIVE}?limit=${limit}&status=active`),
    getDetails: (id) => apiClient.get(API_ENDPOINTS.SIGNALS.DETAILS(id))
};