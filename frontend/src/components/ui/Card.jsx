import React from 'react';
import { twMerge } from 'tailwind-merge';
import { clsx } from 'clsx';

export const Card = ({ children, className, ...props }) => (
  <div
    className={twMerge(clsx(
      'relative overflow-hidden rounded-2xl border border-white/10 bg-[#081426]/85 p-5 shadow-[0_14px_34px_rgba(2,8,23,0.45)] backdrop-blur-sm transition-all duration-200',
      'before:pointer-events-none before:absolute before:inset-0 before:bg-[linear-gradient(135deg,rgba(34,211,238,0.09),transparent_40%,rgba(16,185,129,0.05))] before:opacity-90',
      'hover:border-cyan-400/30 hover:shadow-[0_18px_36px_rgba(8,145,178,0.25)]',
      className,
    ))}
    {...props}
  >
    <div className="relative z-10">{children}</div>
  </div>
);

export default Card;