import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import Login from './Login'
import { useAuthStore } from '../store/useAuthStore'

// Mock useAuthStore
vi.mock('../store/useAuthStore', () => {
  const mockState = {
    login: vi.fn(),
    error: null,
    clearError: vi.fn(),
  }
  return {
    useAuthStore: vi.fn((selector) => selector(mockState)),
  }
})

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const original = await vi.importActual('react-router-dom')
  return {
    ...original,
    useNavigate: () => mockNavigate,
  }
})

describe('Login Component Unit & UI Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders Login form with security gate fields', () => {
    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    )

    expect(screen.getByText('StockAI Pro')).toBeInTheDocument()
    expect(screen.getByText('Institutional Desk Login')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('name@desk.com')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('••••••••••••')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Access Terminal/i })).toBeInTheDocument()
  })

  it('allows user inputs for email and access key keying', () => {
    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    )

    const emailInput = screen.getByPlaceholderText('name@desk.com')
    const passwordInput = screen.getByPlaceholderText('••••••••••••')

    fireEvent.change(emailInput, { target: { value: 'trader@desks.com' } })
    fireEvent.change(passwordInput, { target: { value: 'SuperSecret123' } })

    expect(emailInput.value).toBe('trader@desks.com')
    expect(passwordInput.value).toBe('SuperSecret123')
  })

  it('calls useAuthStore login action and redirects to dashboard on successful auth', async () => {
    const mockLogin = vi.fn().mockResolvedValue(true)
    const mockState = {
      login: mockLogin,
      error: null,
      clearError: vi.fn(),
    }
    vi.mocked(useAuthStore).mockImplementation((selector) => selector(mockState))

    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    )

    const emailInput = screen.getByPlaceholderText('name@desk.com')
    const passwordInput = screen.getByPlaceholderText('••••••••••••')
    const submitBtn = screen.getByRole('button', { name: /Access Terminal/i })

    fireEvent.change(emailInput, { target: { value: 'trader@desks.com' } })
    fireEvent.change(passwordInput, { target: { value: 'SuperSecret123' } })
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith({
        email: 'trader@desks.com',
        password: 'SuperSecret123',
      })
      expect(mockNavigate).toHaveBeenCalledWith('/dashboard')
    })
  })

  it('displays validation / server error when login fails', () => {
    const mockState = {
      login: vi.fn().mockResolvedValue(false),
      error: 'Invalid JWT Access Token credentials',
      clearError: vi.fn(),
    }
    vi.mocked(useAuthStore).mockImplementation((selector) => selector(mockState))

    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    )

    expect(screen.getByText('Invalid JWT Access Token credentials')).toBeInTheDocument()
  })
})
