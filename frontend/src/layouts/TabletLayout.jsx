import React from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { LayoutDashboard, Activity, BarChart2, Briefcase, History, Settings } from 'lucide-react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

export const navigation = [
  { name: 'Dashboard', href: '/dashboard', icon: LayoutDashboard },
  { name: 'Signals', href: '/signals', icon: Activity },
  { name: 'Trades', href: '/trades', icon: BarChart2 },
  { name: 'Portfolio', href: '/portfolio', icon: Briefcase },
  { name: 'History', href: '/history', icon: History },
  { name: 'Settings', href: '/settings', icon: Settings },
];

const SidebarItem = ({ item }) => (
  <NavLink
    to={item.href}
    className={({ isActive }) =>
      cn(
        'group flex flex-col items-center justify-center p-3 my-2 text-sm font-medium rounded-xl transition-all duration-200',
        isActive
          ? 'bg-cyan-500/10 text-cyan-300 shadow-[inset_4px_0_0_0_rgba(6,182,212,1)] shadow-[0_0_12px_rgba(6,182,212,0.15)]'
          : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-250'
      )
    }
    title={item.name}
  >
    <item.icon className="h-6 w-6 flex-shrink-0" />
  </NavLink>
);

export default function TabletLayout({ children }) {
  const location = useLocation();
  const isDashboard = location.pathname === '/dashboard';

  return (
    <div className="flex h-screen bg-[#030914] text-white overflow-hidden font-sans">
      {/* Narrow Sidebar */}
      <div className="w-20 flex flex-col bg-[#060E1D] border-r border-white/10 backdrop-blur-xl z-20 items-center shrink-0">
        <div className="flex h-16 shrink-0 items-center justify-center border-b border-white/10 w-full mb-4">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
             <Activity className="h-6 w-6 text-white" />
          </div>
        </div>
        <div className="flex flex-1 flex-col overflow-y-auto w-full px-2 pb-4 scrollbar-hide items-center">
          <nav className="flex-1 w-full">
            {navigation.map((item) => (
              <SidebarItem key={item.name} item={item} />
            ))}
          </nav>
        </div>
        <div className="p-4 border-t border-white/10 w-full flex justify-center shrink-0">
           <div className="w-10 h-10 rounded-full bg-cyan-900/40 flex items-center justify-center text-cyan-300 font-bold border border-cyan-500/20 cursor-pointer">
              AD
           </div>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex flex-1 flex-col overflow-hidden relative">
        {/* Page Content - Full screen width with custom paddings */}
        <main className={cn(
          "flex-1 overflow-y-auto bg-[#020617]",
          isDashboard ? "p-0 h-full w-full overflow-hidden" : "p-6"
        )}>
          <div className="w-full h-full">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
