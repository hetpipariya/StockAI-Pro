export function formatPrice(n) {
  const val = Number(n)
  if (!Number.isFinite(val)) return '0.00'
  return new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(val)
}

export function formatVolume(n) {
  const val = Number(n)
  if (!Number.isFinite(val) || val === 0) return '0'
  if (val >= 1e6) return (val / 1e6).toFixed(1) + 'M'
  if (val >= 1e3) return (val / 1e3).toFixed(1) + 'K'
  return String(Math.round(val))
}
