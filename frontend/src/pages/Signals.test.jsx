import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import Signals from './Signals'
import { useStore } from '../store/useStore'

// Mock useStore
vi.mock('../store/useStore', () => {
  const mockState = {
    signals: [
      {
        id: 'sig-1',
        symbol: 'SBIN',
        time: '2026-05-29T15:00:00Z',
        signal: 'BUY',
        price: 650.0,
        confidence: 87.0,
        stop_loss: 645.0,
        target: 670.0,
        reason: 'Bullish breakout',
      }
    ],
    currentSignal: null,
    executeTrade: vi.fn(),
    bundleLoading: false,
    selectedTimeframe: '5m',
    balance: 100000.0,
    tradeDecisionBySymbol: {
      SBIN: {
        decision: { status: 'READY' }
      }
    },
    tradeDecisionLoadingBySymbol: {},
    tradeDecisionErrorBySymbol: {},
    evaluateTradeDecision: vi.fn().mockResolvedValue({}),
    liveHealth: 'HEALTHY',
    tradingBlockedByLatency: false,
    liveDataMessage: '',
  }
  return {
    useStore: vi.fn(() => mockState),
  }
})

vi.mock('../components/Toast', () => ({
  useToast: () => ({ showToast: vi.fn() }),
}))

// Mock Sub-components
vi.mock('../components/features/TradeStatusPanel', () => ({
  default: () => <div data-testid="mock-status-panel">Trade Status Panel</div>,
}))

describe('Signals Component Unit & UI Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders Signals page with live triggers list', () => {
    render(<Signals />)

    expect(screen.getByText('Live Signals')).toBeInTheDocument()
    expect(screen.getByText('SBIN')).toBeInTheDocument()
    expect(screen.getByText('BUY')).toBeInTheDocument()
    expect(screen.getByText('₹650.00')).toBeInTheDocument()
  })

  it('displays the execution healthy badge', () => {
    render(<Signals />)

    expect(screen.getByText(/Feed healthy for execution./)).toBeInTheDocument()
  })

  it('opens confirmation dialogue when Execute button is clicked', async () => {
    render(<Signals />)

    const executeBtn = screen.getByRole('button', { name: /Execute Trade/i })
    fireEvent.click(executeBtn)

    expect(screen.getByText('Execute Trade?')).toBeInTheDocument()
    expect(screen.getByText(/Execute BUY for SBIN at ₹650.00?/)).toBeInTheDocument()
  })

  it('calls executeTrade and closes dialog on trade validation', async () => {
    const mockExecute = vi.fn().mockResolvedValue({})
    const mockState = {
      signals: [
        {
          id: 'sig-1',
          symbol: 'SBIN',
          time: '2026-05-29T15:00:00Z',
          signal: 'BUY',
          price: 650.0,
          confidence: 87.0,
          stop_loss: 645.0,
          target: 670.0,
          reason: 'Bullish breakout',
        }
      ],
      currentSignal: null,
      executeTrade: mockExecute,
      bundleLoading: false,
      selectedTimeframe: '5m',
      balance: 100000.0,
      tradeDecisionBySymbol: {
        SBIN: {
          decision: { status: 'READY' }
        }
      },
      tradeDecisionLoadingBySymbol: {},
      tradeDecisionErrorBySymbol: {},
      evaluateTradeDecision: vi.fn().mockResolvedValue({}),
      liveHealth: 'HEALTHY',
      tradingBlockedByLatency: false,
      liveDataMessage: '',
    }
    vi.mocked(useStore).mockImplementation(() => mockState)

    render(<Signals />)

    const executeBtn = screen.getByRole('button', { name: /Execute Trade/i })
    fireEvent.click(executeBtn)

    const confirmBtn = screen.getByRole('button', { name: 'Execute' })
    fireEvent.click(confirmBtn)

    await waitFor(() => {
      expect(mockExecute).toHaveBeenCalled()
    })
  })
})
