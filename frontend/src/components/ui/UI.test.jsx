import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, test, expect, vi } from 'vitest';
import Button from './Button';
import Badge from './Badge';
import Card from './Card';

describe('UI Button Component', () => {
  test('renders children and variant classes', () => {
    render(<Button variant="primary">Click Me</Button>);
    expect(screen.getByText('Click Me')).toBeInTheDocument();
    
    const button = screen.getByRole('button');
    expect(button).toHaveClass('border-cyan-400/45');
  });

  test('renders different variants and sizes', () => {
    const { rerender } = render(<Button variant="secondary" size="sm">Secondary Sm</Button>);
    let button = screen.getByRole('button');
    expect(button).toHaveClass('text-slate-100');

    rerender(<Button variant="outline" size="lg">Outline Lg</Button>);
    button = screen.getByRole('button');
    expect(button).toHaveClass('text-cyan-200');

    rerender(<Button variant="ghost">Ghost</Button>);
    button = screen.getByRole('button');
    expect(button).toHaveClass('text-slate-300');

    rerender(<Button variant="danger">Danger</Button>);
    button = screen.getByRole('button');
    expect(button).toHaveClass('text-rose-100');
  });

  test('triggers onClick when clicked and not blocked', () => {
    const handleClick = vi.fn();
    render(<Button onClick={handleClick}>Trigger</Button>);
    fireEvent.click(screen.getByRole('button'));
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  test('prevents click when disabled', () => {
    const handleClick = vi.fn();
    render(<Button disabled onClick={handleClick}>Disabled</Button>);
    fireEvent.click(screen.getByRole('button'));
    expect(handleClick).not.toHaveBeenCalled();
    expect(screen.getByRole('button')).toBeDisabled();
  });

  test('renders loading state and disables button', () => {
    const handleClick = vi.fn();
    render(<Button isLoading loadingText="Saving..." onClick={handleClick}>Submit</Button>);
    expect(screen.getByText('Saving...')).toBeInTheDocument();
    expect(screen.getByRole('button')).toBeDisabled();
  });

  test('renders success state and disables button', () => {
    const handleClick = vi.fn();
    render(<Button isSuccess onClick={handleClick}>Submit</Button>);
    expect(screen.getByText('Verified')).toBeInTheDocument();
    expect(screen.getByRole('button')).toBeDisabled();
  });
});

describe('UI Badge Component', () => {
  test('renders default state and classes', () => {
    render(<Badge>Pending</Badge>);
    expect(screen.getByText('Pending')).toBeInTheDocument();
  });

  test('renders variants correctly', () => {
    const { rerender } = render(<Badge variant="buy">BUY</Badge>);
    let badge = screen.getByText('BUY');
    expect(badge).toHaveClass('text-emerald-200');

    rerender(<Badge variant="sell">SELL</Badge>);
    badge = screen.getByText('SELL');
    expect(badge).toHaveClass('text-rose-200');

    rerender(<Badge variant="info">INFO</Badge>);
    badge = screen.getByText('INFO');
    expect(badge).toHaveClass('text-cyan-200');

    rerender(<Badge variant="warning">WARN</Badge>);
    badge = screen.getByText('WARN');
    expect(badge).toHaveClass('text-amber-200');

    rerender(<Badge variant="unknown">UNKNOWN</Badge>);
    badge = screen.getByText('UNKNOWN');
    expect(badge).toHaveClass('text-slate-200');
  });
});

describe('UI Card Component', () => {
  test('renders child elements and defaults', () => {
    render(
      <Card>
        <div>Card Content</div>
      </Card>
    );
    expect(screen.getByText('Card Content')).toBeInTheDocument();
  });
});
