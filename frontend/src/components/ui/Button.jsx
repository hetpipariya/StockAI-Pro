import React from "react";
import { Loader2, CheckCircle } from "lucide-react";

export const Button = ({
  children,
  onClick,
  type = "button",
  disabled = false,
  isLoading = false,
  isSuccess = false,
  variant = "primary", // primary, secondary, outline, ghost
  className = "",
  size = "default", // sm, default, lg
}) => {
  const baseClasses =
    "relative font-semibold flex items-center justify-center overflow-hidden transition-all duration-300 ease-out transform active:scale-[0.98] outline-none rounded-lg";
  
  const sizeClasses = {
    sm: "py-1.5 px-3 text-xs",
    default: "py-2.5 px-5 text-sm",
    lg: "py-3.5 px-6 text-base",
  };

  const variantClasses = {
    primary:
      "bg-[#1e2532] text-white border border-[#2e374a] shadow-[0_4px_12px_rgba(0,0,0,0.3)] hover:bg-[#252d3d] hover:border-[#384358] hover:shadow-[0_6px_16px_rgba(0,0,0,0.4)] hover:-translate-y-[1px]",
    secondary:
      "bg-[#0d121c] text-slate-300 border border-slate-800 hover:bg-[#121926] hover:border-slate-700 hover:text-white shadow-sm",
    outline:
      "bg-transparent text-cyan-400 border border-cyan-500/30 hover:bg-cyan-500/10 hover:border-cyan-400/50 shadow-[0_0_10px_rgba(34,211,238,0.05)]",
    ghost:
      "bg-transparent text-slate-400 hover:text-white hover:bg-slate-800/50 border border-transparent",
  };

  const disabledClasses =
    "bg-[#0f141e] text-slate-600 cursor-not-allowed border-[#1a2233] shadow-none hover:translate-y-0 active:scale-100";
  
  const successClasses =
    "bg-emerald-500/10 border-emerald-500/30 text-emerald-400 shadow-[0_0_15px_rgba(16,185,129,0.2)] filter-none hover:translate-y-0 cursor-default active:scale-100";

  const getCombinedClasses = () => {
    let classes = `${baseClasses} ${sizeClasses[size]}`;
    
    if (isSuccess) {
      classes += ` ${successClasses}`;
    } else if (disabled || isLoading) {
      classes += ` ${disabledClasses}`;
    } else {
      classes += ` ${variantClasses[variant]}`;
    }
    
    return `${classes} ${className}`;
  };

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || isLoading || isSuccess}
      className={getCombinedClasses()}
    >
      <div className="relative z-10 flex items-center justify-center gap-2">
        {isSuccess ? (
          <>
            <CheckCircle className="h-4 w-4 animate-in zoom-in duration-300" />
            <span className="animate-in slide-in-from-right-2 duration-300">
              Verified
            </span>
          </>
        ) : isLoading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin text-cyan-400" />
            <span className="animate-in fade-in duration-300 text-slate-300">
              Signing in...
            </span>
          </>
        ) : (
          children
        )}
      </div>

      {/* Subtle top highlight for depth */}
      {(!disabled && !isSuccess && variant === "primary") && (
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/10 to-transparent opacity-50"></div>
      )}
      
      {/* Ripple/Glow effect base layer */}
      {(!disabled && !isSuccess && variant === "primary") && (
        <div className="absolute inset-0 bg-cyan-400/5 opacity-0 active:opacity-100 transition-opacity duration-150 mix-blend-overlay"></div>
      )}
    </button>
  );
};

export default Button;

