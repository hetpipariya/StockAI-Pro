import React from 'react'
import { render, screen } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import Portfolio from './Portfolio'
import { useStore } from '../store/useStore'

// Mock useStore
vi.mock('../store/useStore', () => {
  const mockState = {
    balance: 105500.0,
    winRate: 64.5,
    todaysPnL: 850.0,
    activeTrades: [
      { id: 't1', symbol: 'SBIN', entryPrice: 640.0, size: 10 },
    ],
  }
  return {
    useStore: vi.fn(() => mockState),
  }
})

describe('Portfolio Component Unit & UI Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders Portfolio details with starting and current capital', () => {
    render(<Portfolio />)

    expect(screen.getByText('Starting Capital')).toBeInTheDocument()
    expect(screen.getByText('₹1,00,000')).toBeInTheDocument()
    expect(screen.getByText('Current Capital')).toBeInTheDocument()
    expect(screen.getByText('₹1,05,500')).toBeInTheDocument()
  })

  it('calculates and renders return percentage successfully', () => {
    render(<Portfolio />)

    expect(screen.getByText('Return')).toBeInTheDocument()
    // 105500 is 5.5% return over 100000 baseline
    expect(screen.getByText('+5.50%')).toBeInTheDocument()
  })

  it('calculates gross exposure from active positions', () => {
    render(<Portfolio />)

    expect(screen.getByText('Gross Exposure')).toBeInTheDocument()
    // 640.0 * 10 = 6400
    expect(screen.getByText('₹6,400')).toBeInTheDocument()
  })

  it('displays the desk metrics details', () => {
    render(<Portfolio />)

    expect(screen.getByText('Performance Matrix')).toBeInTheDocument()
    expect(screen.getByText('Win Rate')).toBeInTheDocument()
    expect(screen.getByText('64.5%')).toBeInTheDocument()
    expect(screen.getByText('+₹850.00')).toBeInTheDocument()
    expect(screen.getByText('Open Positions')).toBeInTheDocument()
    // 1 active trade
    expect(screen.getByText('1')).toBeInTheDocument()
  })
})
