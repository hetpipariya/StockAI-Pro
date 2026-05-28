// Types Index
export interface User {
  id: string;
  email: string;
  firstName: string;
  lastName: string;
  avatar?: string;
  settings?: Settings;
  createdAt?: string;
  updatedAt?: string;
}

export interface Settings {
  theme: 'dark' | 'light';
  notifications: boolean;
  emailAlerts: boolean;
  riskLevel: 'conservative' | 'moderate' | 'aggressive';
  [key: string]: any;
}

export interface AuthResponse {
  access_token: string;
  refresh_token?: string;
  user: User;
}

export interface Stock {
  id?: string;
  symbol: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
  high: number;
  low: number;
  open: number;
  close: number;
  volume: number;
  marketCap?: number;
  peRatio?: number;
  dividend?: number;
  timestamp: number;
}

export interface PriceData {
  symbol: string;
  price: number;
  change: number;
  changePercent: number;
  high: number;
  low: number;
  volume: number;
  timestamp: number;
}

export interface OHLCV {
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  timestamp: number;
}

export interface MarketStatus {
  status: 'open' | 'closed' | 'pre-market' | 'after-hours';
  indices: {
    [key: string]: {
      value: number;
      change: number;
      changePercent: number;
    };
  };
  timestamp: number;
}

export type SignalAction = 'BUY' | 'SELL' | 'HOLD';
export type SignalFilter = 'buy' | 'sell' | 'hold' | 'all';
export type Timeframe = '1m' | '5m' | '15m' | '1h' | '4h' | '1d' | '1w' | '1M';

export interface Signal {
  id: string;
  symbol: string;
  action: SignalAction;
  confidence: number;
  timeframe: Timeframe;
  indicators: {
    [key: string]: any;
  };
  generatedAt: number;
  price: number;
  reason?: string;
}

export interface SignalFilters {
  action?: SignalAction;
  confidence?: number;
  timeframe?: Timeframe;
  symbol?: string;
}

export interface Position {
  id: string;
  symbol: string;
  quantity: number;
  entryPrice: number;
  currentPrice: number;
  costBasis: number;
  currentValue: number;
  unrealizedGain: number;
  unrealizedGainPercent: number;
  realizedGain?: number;
  entryDate: number;
  exitDate?: number;
  status: 'open' | 'closed';
}

export interface Portfolio {
  id?: string;
  userId?: string;
  totalValue: number;
  totalCost: number;
  totalGain: number;
  totalGainPercent: number;
  cashBalance: number;
  positions: Position[];
  createdAt?: number;
  updatedAt?: number;
}

export type NotificationType = 'info' | 'success' | 'error' | 'warning';

export interface Notification {
  id: string;
  message: string;
  type: NotificationType;
  duration?: number;
  timestamp?: number;
}

export interface ApiResponse<T = any> {
  success: boolean;
  data?: T;
  message?: string;
  error?: string;
  timestamp?: number;
}

export interface PaginatedResponse<T = any> {
  data: T[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
}

export interface WatchlistItem {
  symbol: string;
  addedAt: number;
  notes?: string;
}
