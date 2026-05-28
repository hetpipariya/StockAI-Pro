import React from 'react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export const Badge = ({ children, variant = 'default', className }) => {
  const variants = {
    buy: 'border-emerald-300/40 bg-emerald-400/15 text-emerald-200',
    sell: 'border-rose-300/40 bg-rose-400/15 text-rose-200',
    default: 'border-slate-500/45 bg-slate-500/15 text-slate-200',
    info: 'border-cyan-300/45 bg-cyan-400/15 text-cyan-200',
    warning: 'border-amber-300/45 bg-amber-400/15 text-amber-200',
  };

  return (
    <span
      className={twMerge(clsx(
        'inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.08em]',
        variants[variant] || variants.default,
        className,
      ))}
    >
      {children}
    </span>
  );
};

export default Badge;