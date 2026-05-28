import React from 'react';

export default function DesktopLayout({ children }) {
  return (
    <div className="w-full h-screen bg-[#050816] text-slate-100 overflow-hidden font-sans select-none relative">
      {children}
    </div>
  );
}
