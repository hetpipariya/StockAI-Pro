/**
 * Formatting Utilities
 * Functions for formatting currency, prices, percentages, volumes, and large amounts
 */

/**
 * Format a number as Indian Rupees (INR)
 * @param value - Number to format
 * @param decimals - Number of decimal places (default: 0)
 * @returns Formatted currency string
 * @example formatINR(1000) => "₹1,000"
 * @example formatINR(1500.50) => "₹1,500.50"
 */
export function formatINR(value: number, decimals: number = 0): string {
  if (typeof value !== 'number' || isNaN(value)) return '₹0';

  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

/**
 * Format stock price with fixed 2 decimal places
 * @param price - Price value
 * @returns Formatted price string
 * @example formatPrice(150.5) => "150.50"
 * @example formatPrice(100) => "100.00"
 */
export function formatPrice(price: number): string {
  if (typeof price !== 'number' || isNaN(price)) return '0.00';
  return price.toFixed(2);
}

/**
 * Format percentage with +/- sign
 * @param pct - Percentage value (e.g., 5.25 for 5.25%)
 * @param decimals - Number of decimal places (default: 2)
 * @returns Formatted percentage string
 * @example formatPercent(5.25) => "+5.25%"
 * @example formatPercent(-2.5) => "-2.50%"
 * @example formatPercent(0) => "0.00%"
 */
export function formatPercent(pct: number, decimals: number = 2): string {
  if (typeof pct !== 'number' || isNaN(pct)) return '0.00%';

  const sign = pct > 0 ? '+' : pct < 0 ? '' : '';
  const formatted = Math.abs(pct).toFixed(decimals);
  return `${sign}${formatted}%`;
}

/**
 * Format large volume numbers (Crores, Lakhs, Thousands)
 * @param volume - Volume value
 * @param decimals - Number of decimal places (default: 2)
 * @returns Formatted volume string
 * @example formatVolume(1000000) => "10.00L"
 * @example formatVolume(10000000) => "1.00Cr"
 * @example formatVolume(500000) => "5.00L"
 * @example formatVolume(1500) => "1.50K"
 */
export function formatVolume(volume: number, decimals: number = 2): string {
  if (typeof volume !== 'number' || isNaN(volume)) return '0';

  if (Math.abs(volume) >= 10000000) {
    // Crores (Cr) - 1,00,00,000+
    return (volume / 10000000).toFixed(decimals) + 'Cr';
  } else if (Math.abs(volume) >= 100000) {
    // Lakhs (L) - 1,00,000+
    return (volume / 100000).toFixed(decimals) + 'L';
  } else if (Math.abs(volume) >= 1000) {
    // Thousands (K) - 1,000+
    return (volume / 1000).toFixed(decimals) + 'K';
  }

  return volume.toString();
}

/**
 * Format large INR amounts in compact form (Crores, Lakhs)
 * @param value - Amount in INR
 * @param decimals - Number of decimal places (default: 2)
 * @returns Formatted amount string
 * @example formatLargeINR(100000000) => "₹10.00Cr"
 * @example formatLargeINR(5000000) => "₹50.00L"
 * @example formatLargeINR(500000) => "₹5.00L"
 */
export function formatLargeINR(value: number, decimals: number = 2): string {
  if (typeof value !== 'number' || isNaN(value)) return '₹0';

  const absValue = Math.abs(value);
  let formattedValue: string;

  if (absValue >= 10000000) {
    // Crores (Cr)
    formattedValue = (value / 10000000).toFixed(decimals) + 'Cr';
  } else if (absValue >= 100000) {
    // Lakhs (L)
    formattedValue = (value / 100000).toFixed(decimals) + 'L';
  } else {
    // Regular rupees
    formattedValue = new Intl.NumberFormat('en-IN', {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(value);
  }

  return `₹${formattedValue}`;
}

/**
 * Format timestamp to readable date format
 * @param timestamp - Unix timestamp in milliseconds or ISO string
 * @param format - Format style: 'short', 'long', 'time'
 * @returns Formatted date string
 * @example formatDate(Date.now()) => "21 Nov"
 * @example formatDate(Date.now(), 'long') => "21 November 2024"
 * @example formatDate(Date.now(), 'time') => "14:30"
 */
export function formatDate(
  timestamp: number | string,
  format: 'short' | 'long' | 'time' = 'short'
): string {
  const date = typeof timestamp === 'string' ? new Date(timestamp) : new Date(timestamp);

  if (isNaN(date.getTime())) return 'Invalid date';

  if (format === 'time') {
    return date.toLocaleTimeString('en-IN', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  }

  if (format === 'long') {
    return date.toLocaleDateString('en-IN', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });
  }

  // short format: "21 Nov"
  return date.toLocaleDateString('en-IN', {
    month: 'short',
    day: 'numeric',
  });
}

/**
 * Format DateTime to readable format with time
 * @param timestamp - Unix timestamp or ISO string
 * @returns Formatted date-time string
 * @example formatDateTime(Date.now()) => "21 Nov, 14:30"
 */
export function formatDateTime(timestamp: number | string): string {
  const date = typeof timestamp === 'string' ? new Date(timestamp) : new Date(timestamp);

  if (isNaN(date.getTime())) return 'Invalid date';

  const dateStr = date.toLocaleDateString('en-IN', {
    month: 'short',
    day: 'numeric',
  });

  const timeStr = date.toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });

  return `${dateStr}, ${timeStr}`;
}

/**
 * Format a duration in milliseconds to human-readable format
 * @param ms - Duration in milliseconds
 * @returns Formatted duration string
 * @example formatDuration(5000) => "5s"
 * @example formatDuration(65000) => "1m 5s"
 * @example formatDuration(3665000) => "1h 1m"
 */
export function formatDuration(ms: number): string {
  if (typeof ms !== 'number' || isNaN(ms) || ms < 0) return '0s';

  const seconds = Math.floor((ms / 1000) % 60);
  const minutes = Math.floor((ms / (1000 * 60)) % 60);
  const hours = Math.floor(ms / (1000 * 60 * 60));

  const parts: string[] = [];

  if (hours > 0) parts.push(`${hours}h`);
  if (minutes > 0) parts.push(`${minutes}m`);
  if (seconds > 0 || parts.length === 0) parts.push(`${seconds}s`);

  return parts.join(' ');
}

/**
 * Format a number with commas (Indian numbering system)
 * @param value - Number to format
 * @param decimals - Number of decimal places
 * @returns Formatted number string
 * @example formatNumber(1000000) => "10,00,000"
 * @example formatNumber(1234567.89, 2) => "12,34,567.89"
 */
export function formatNumber(value: number, decimals?: number): string {
  if (typeof value !== 'number' || isNaN(value)) return '0';

  const options: Intl.NumberFormatOptions = {
    minimumFractionDigits: decimals !== undefined ? decimals : 0,
    maximumFractionDigits: decimals !== undefined ? decimals : 0,
  };

  return new Intl.NumberFormat('en-IN', options).format(value);
}

/**
 * Get color class based on value direction (up/down/neutral)
 * @param value - Numeric value to determine direction
 * @returns CSS color class name
 * @example getChangeColor(5.2) => "text-success"
 * @example getChangeColor(-2.1) => "text-danger"
 * @example getChangeColor(0) => "text-muted"
 */
export function getChangeColor(value: number): 'text-success' | 'text-danger' | 'text-muted' {
  if (value > 0) return 'text-success';
  if (value < 0) return 'text-danger';
  return 'text-muted';
}

/**
 * Get color class based on status
 * @param status - Status string
 * @returns CSS color class name
 * @example getStatusColor('active') => "text-success"
 * @example getStatusColor('error') => "text-danger"
 */
export function getStatusColor(
  status: 'active' | 'inactive' | 'pending' | 'error' | 'warning'
): string {
  switch (status) {
    case 'active':
      return 'text-success';
    case 'error':
      return 'text-danger';
    case 'warning':
      return 'text-warning';
    case 'pending':
      return 'text-info';
    case 'inactive':
    default:
      return 'text-muted';
  }
}
