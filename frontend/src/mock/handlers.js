import { http, HttpResponse } from 'msw'

export const handlers = [
  // Mock login
  http.post('*/api/v1/auth/login', () => {
    return HttpResponse.json({
      status: 'success',
      data: {
        access_token: 'mock-access-token-jwt',
        refresh_token: 'mock-refresh-token-jwt',
        user: {
          id: '1',
          email: 'test_user@example.com',
          full_name: 'Test User',
          is_active: true,
          role: 'user',
        },
      },
    })
  }),

  // Mock register
  http.post('*/api/v1/auth/register', () => {
    return HttpResponse.json({
      status: 'success',
      data: {
        access_token: 'mock-access-token-jwt',
        refresh_token: 'mock-refresh-token-jwt',
        user: {
          id: '1',
          email: 'test_user@example.com',
          full_name: 'Test User',
          is_active: true,
          role: 'user',
        },
      },
    })
  }),

  // Mock profile / me
  http.get('*/api/v1/auth/profile', () => {
    return HttpResponse.json({
      id: '1',
      email: 'test_user@example.com',
      full_name: 'Test User',
      is_active: true,
      role: 'user',
    })
  }),

  // Mock logout
  http.post('*/api/v1/auth/logout', () => {
    return HttpResponse.json({ status: 'success' })
  }),

  // Mock portfolio balance
  http.get('*/api/v1/portfolio/balance', () => {
    return HttpResponse.json({
      available_capital: 100000.0,
      total_equity: 100000.0,
      daily_pnl: 250.0,
      daily_pnl_pct: 0.25,
      open_positions_count: 1,
    })
  }),

  // Mock active signals
  http.get('*/api/v1/signals', () => {
    return HttpResponse.json([
      {
        id: 'sig-1',
        symbol: 'SBIN',
        time: '2026-05-29T15:00:00Z',
        signal: 'BUY',
        probability: 0.87,
        stop_loss: 645.0,
        target: 670.0,
        reason: 'Bullish candle confluence and volume breakout',
      },
      {
        id: 'sig-2',
        symbol: 'RELIANCE',
        time: '2026-05-29T15:05:00Z',
        signal: 'HOLD',
        probability: 0.52,
        stop_loss: 2480.0,
        target: 2550.0,
        reason: 'Doji indecision overrules signal alignment',
      },
    ])
  }),
]
