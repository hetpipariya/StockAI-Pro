import React, { useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export const Input = ({
  icon: Icon,
  label,
  type = 'text',
  value,
  onChange,
  onFocus,
  onBlur,
  placeholder,
  hasError,
  showPasswordToggle,
  onTogglePassword,
  isPasswordVisible,
  autoComplete,
  className,
}) => {
  const [isFocused, setIsFocused] = useState(false);

  const handleFocus = (event) => {
    setIsFocused(true);
    if (onFocus) onFocus(event);
  };

  const handleBlur = (event) => {
    setIsFocused(false);
    if (onBlur) onBlur(event);
  };

  return (
    <div className="group relative flex w-full flex-col gap-2">
      {label ? (
        <label
          className={twMerge(clsx(
            'text-[11px] font-semibold uppercase tracking-[0.14em] transition-colors',
            hasError ? 'text-rose-300' : isFocused ? 'text-cyan-200' : 'text-slate-400',
          ))}
        >
          {label}
        </label>
      ) : null}

      <div
        className={twMerge(clsx(
          'relative flex items-center overflow-hidden rounded-xl border bg-[#081528] transition-all duration-200',
          'before:pointer-events-none before:absolute before:inset-0 before:bg-[linear-gradient(120deg,rgba(34,211,238,0.08),transparent_45%)]',
          hasError
            ? 'border-rose-400/45 shadow-[0_0_0_3px_rgba(244,63,94,0.15)]'
            : isFocused
              ? 'border-cyan-300/55 shadow-[0_0_0_3px_rgba(34,211,238,0.16)]'
              : 'border-white/10 hover:border-cyan-300/35',
          className,
        ))}
      >
        {Icon ? (
          <div className="pointer-events-none absolute left-3 z-10 flex items-center justify-center">
            <Icon
              className={twMerge(clsx(
                'h-4 w-4 transition-colors',
                hasError ? 'text-rose-300' : isFocused ? 'text-cyan-200' : 'text-slate-500',
              ))}
            />
          </div>
        ) : null}

        <input
          type={showPasswordToggle && isPasswordVisible ? 'text' : type}
          value={value}
          onChange={onChange}
          onFocus={handleFocus}
          onBlur={handleBlur}
          placeholder={placeholder}
          autoComplete={autoComplete}
          className={twMerge(clsx(
            'relative z-10 w-full bg-transparent py-3 text-sm font-medium text-slate-100 placeholder:text-slate-500 outline-none',
            Icon ? 'pl-10' : 'pl-3.5',
            showPasswordToggle ? 'pr-11' : 'pr-3.5',
          ))}
        />

        {showPasswordToggle ? (
          <button
            type="button"
            onClick={onTogglePassword}
            className="absolute right-2 z-10 rounded-md p-1.5 text-slate-400 transition-colors hover:bg-white/10 hover:text-cyan-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/45"
            aria-label={isPasswordVisible ? 'Hide password' : 'Show password'}
          >
            {isPasswordVisible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        ) : null}
      </div>
    </div>
  );
};

export default Input;

