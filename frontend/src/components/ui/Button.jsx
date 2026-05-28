import React from 'react';
import { Loader2, CheckCircle2 } from 'lucide-react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export const Button = ({
  children,
  onClick,
  type = 'button',
  disabled = false,
  isLoading = false,
  loadingText = 'Loading...',
  isSuccess = false,
  variant = 'primary',
  className = '',
  size = 'default',
  ...props
}) => {
  const isBlocked = disabled || isLoading || isSuccess;

  const sizeClasses = {
    sm: 'h-8 px-3 text-xs',
    default: 'h-10 px-4 text-sm',
    lg: 'h-12 px-5 text-base',
  };

  const variantClasses = {
    primary: 'border-cyan-400/45 bg-gradient-to-r from-cyan-400/25 via-cyan-300/10 to-emerald-300/20 text-cyan-50 shadow-[0_10px_26px_rgba(34,211,238,0.2)] hover:border-cyan-300/70 hover:shadow-[0_12px_28px_rgba(16,185,129,0.26)]',
    secondary: 'border-slate-600/60 bg-slate-900/70 text-slate-100 shadow-[0_8px_20px_rgba(2,6,23,0.45)] hover:border-slate-500/70 hover:bg-slate-800/80',
    outline: 'border-cyan-400/45 bg-transparent text-cyan-200 hover:bg-cyan-500/10 hover:text-cyan-100',
    ghost: 'border-transparent bg-transparent text-slate-300 hover:bg-white/10 hover:text-white',
    danger: 'border-rose-400/45 bg-rose-500/15 text-rose-100 shadow-[0_10px_24px_rgba(244,63,94,0.24)] hover:border-rose-300/70 hover:bg-rose-500/25',
  };

  const stateClasses = isSuccess
    ? 'cursor-default border-emerald-400/50 bg-emerald-500/20 text-emerald-100 shadow-[0_0_22px_rgba(16,185,129,0.28)]'
    : isBlocked
      ? 'cursor-not-allowed border-slate-700/60 bg-slate-900/70 text-slate-500 shadow-none'
      : variantClasses[variant] || variantClasses.primary;

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={isBlocked}
      className={twMerge(clsx(
        'group relative inline-flex items-center justify-center gap-2 overflow-hidden rounded-xl border font-semibold tracking-wide transition-all duration-200 ease-out',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/40 focus-visible:ring-offset-2 focus-visible:ring-offset-[#060C18]',
        !isBlocked && 'active:scale-[0.99] hover:-translate-y-[1px]',
        sizeClasses[size] || sizeClasses.default,
        stateClasses,
        className,
      ))}
      {...props}
    >
      {!isBlocked && variant === 'primary' ? (
        <span className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_20%_-15%,rgba(255,255,255,0.28),transparent_42%)] opacity-70" />
      ) : null}

      <span className="relative z-10 inline-flex items-center gap-2">
        {isSuccess ? (
          <>
            <CheckCircle2 className="h-4 w-4" />
            <span>Verified</span>
          </>
        ) : isLoading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>{loadingText}</span>
          </>
        ) : (
          children
        )}
      </span>
    </button>
  );
};

export default Button;

