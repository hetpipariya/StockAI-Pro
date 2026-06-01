import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import Dashboard from './Dashboard'
import { useStore } from '../store/useStore.js'
import { useLivePrice } from '../context/LivePriceContext'

// Setup mocks
vi.mock('../store/useStore.js', () => {
  const mockState = {
    selectedSymbol: 'SBIN',
    selectedTimeframe: '5m',
    symbolCatalog: ['SBIN', 'RELIANCE'],
    candles: [],
    snapshot: { ltp: 650.0 },
    indicators: {},
    currentSignal: { symbol: 'SBIN', signal: 'BUY', entry: 648.0, stopLoss: 640.0, target: 665.0 },
    bundleLoading: false,
    bundleError: null,
    bundleWarnings: [],
    loadSymbolCatalog: vi.fn(),
    loadSymbolBundle: vi.fn(),
    selectTimeframe: vi.fn(),
  }
  return {
    useStore: vi.fn((selector) => selector(mockState)),
  }
})

vi.mock('../context/LivePriceContext', () => {
  const mockContext = {
    currentPrice: 650.0,
    dataSource: 'NSE_API',
    connectionStatus: 'CONNECTED',
  }
  return {
    useLivePrice: vi.fn(() => mockContext),
  }
})

vi.mock('../api/websocket.js', () => ({
  wsManager: {
    subscribe: vi.fn(),
    unsubscribe: vi.fn(),
  },
}))

vi.mock('../components/dashboard/CandlestickChart', () => ({
  default: () => <div data-testid="mock-chart">Mock Candlestick Chart</div>,
}))

vi.mock('../components/dashboard/Topbar', () => ({
  default: ({ handleSelectSymbol }) => (
    <div data-testid="mock-topbar">
      Topbar Terminal
      <button onClick={() => handleSelectSymbol('RELIANCE')}>Select RELIANCE</button>
    </div>
  ),
}))

vi.mock('../components/dashboard/Bottombar', () => ({
  default: () => <div data-testid="mock-bottombar">Bottombar Status</div>,
}))

vi.mock('../components/dashboard/AiTerminalPanel', () => ({
  default: () => <div data-testid="mock-ai-panel">AI Panel Intel</div>,
}))

vi.mock('../components/Toast', () => ({
  useToast: () => ({ showToast: vi.fn() }),
}))

describe('Dashboard Component Unit & UI Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders dashboard with topbar, bottombar, charts, and AI terminal panels', () => {
    render(<Dashboard />)

    expect(screen.getByTestId('mock-topbar')).toBeInTheDocument()
    expect(screen.getByTestId('mock-bottombar')).toBeInTheDocument()
    expect(screen.getByTestId('mock-chart')).toBeInTheDocument()
    expect(screen.getByTestId('mock-ai-panel')).toBeInTheDocument()
  })

  it('displays the active selected symbol and source in header', () => {
    render(<Dashboard />)

    expect(screen.getByText('SBIN')).toBeInTheDocument()
    expect(screen.getByText('(NSE_API)')).toBeInTheDocument()
  })

  it('triggers select symbol bundle loader on Topbar symbol select action', async () => {
    const mockLoadBundle = vi.fn().mockResolvedValue({})
    const mockState = {
      selectedSymbol: 'SBIN',
      selectedTimeframe: '5m',
      symbolCatalog: ['SBIN', 'RELIANCE'],
      candles: [],
      snapshot: { ltp: 650.0 },
      indicators: {},
      currentSignal: null,
      bundleLoading: false,
      bundleError: null,
      bundleWarnings: [],
      loadSymbolCatalog: vi.fn(),
      loadSymbolBundle: mockLoadBundle,
      selectTimeframe: vi.fn(),
    }
    vi.mocked(useStore).mockImplementation((selector) => selector(mockState))

    render(<Dashboard />)

    const selectBtn = screen.getByRole('button', { name: /Select RELIANCE/i })
    fireEvent.click(selectBtn)

    await waitFor(() => {
      expect(mockLoadBundle).toHaveBeenCalledWith('RELIANCE', '5m')
    })
  })

  it('displays reconnect overlays during socket drops', () => {
    const mockContext = {
      currentPrice: 650.0,
      dataSource: 'NSE_API',
      connectionStatus: 'RECONNECTING',
    }
    vi.mocked(useLivePrice).mockImplementation(() => mockContext)

    render(<Dashboard />)

    expect(screen.getByText('RECONNECTING LIVE FEED...')).toBeInTheDocument()
  })

  it('displays degraded API polling backup notice during failed connections', () => {
    const mockContext = {
      currentPrice: 650.0,
      dataSource: 'NSE_API',
      connectionStatus: 'FAILED',
    }
    vi.mocked(useLivePrice).mockImplementation(() => mockContext)

    render(<Dashboard />)

    expect(screen.getByText('LIVE STREAM DISCONNECTED')).toBeInTheDocument()
    expect(screen.getByText(/degraded API polling backup/i)).toBeInTheDocument()
  })
})
