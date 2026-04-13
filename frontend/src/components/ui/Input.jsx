import React, { useState } from "react";
import { Eye, EyeOff } from "lucide-react";

export const Input = ({
  icon: Icon,
  label,
  type = "text",
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
}) => {
  const [isFocused, setIsFocused] = useState(false);

  const handleFocus = (e) => {
    setIsFocused(true);
    if (onFocus) onFocus(e);
  };

  const handleBlur = (e) => {
    setIsFocused(false);
    if (onBlur) onBlur(e);
  };

  return (
    <div className="flex flex-col gap-2 relative group w-full">
      {label && (
        <label
          className={`text-xs font-semibold tracking-wide transition-colors duration-300 ${
            hasError
              ? "text-red-400"
              : isFocused
              ? "text-cyan-400 drop-shadow-[0_0_8px_rgba(34,211,238,0.3)]"
              : "text-slate-300 hover:text-slate-200"
          }`}
        >
          {label}
        </label>
      )}
      <div
        className={`relative flex items-center bg-[#0d121c] rounded-lg border transition-all duration-300 ease-out transform ${
          isFocused ? "scale-[1.01]" : "scale-100"
        } ${
          hasError
            ? "border-red-500/50 shadow-[0_0_12px_rgba(239,68,68,0.2)]"
            : isFocused
            ? "border-cyan-500/50 shadow-[0_0_15px_rgba(34,211,238,0.15)] bg-[#0f1624]"
            : "border-slate-800 shadow-[0_2px_8px_rgba(0,0,0,0.2)] hover:border-slate-700 hover:bg-[#0f1624]"
        }`}
      >
        {Icon && (
          <div className="absolute left-3.5 z-10 flex items-center justify-center pointer-events-none">
            <Icon
              className={`h-4 w-4 transition-colors duration-300 ${
                hasError
                  ? "text-red-400"
                  : isFocused
                  ? "text-cyan-400"
                  : "text-slate-500 group-hover:text-slate-400"
              }`}
            />
          </div>
        )}
        <input
          type={showPasswordToggle && isPasswordVisible ? "text" : type}
          value={value}
          onChange={onChange}
          onFocus={handleFocus}
          onBlur={handleBlur}
          placeholder={placeholder}
          autoComplete={autoComplete}
          className={`w-full bg-transparent text-slate-100 placeholder-slate-600 font-medium py-3 outline-none transition-all duration-300 ${
            Icon ? "pl-10 text-sm" : "pl-3.5 text-sm"
          } ${showPasswordToggle ? "pr-11" : "pr-3.5"}`}
        />
        {showPasswordToggle && (
          <button
            type="button"
            onClick={onTogglePassword}
            className="absolute right-2 p-1.5 rounded-md text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors z-10 focus:outline-none focus:ring-1 focus:ring-cyan-500/50"
            aria-label={isPasswordVisible ? "Hide password" : "Show password"}
          >
            {isPasswordVisible ? (
              <EyeOff className="h-4 w-4" />
            ) : (
              <Eye className="h-4 w-4" />
            )}
          </button>
        )}
      </div>
    </div>
  );
};

export default Input;

