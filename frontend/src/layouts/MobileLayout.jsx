import React from 'react';
import { NavLink } from 'react-router-dom';
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
  { name: 'Settings', href: '/settings', icon: Settings },
];

const BottomNavItem = ({ item }) => (
  <NavLink
    to={item.href}
    className={({ isActive }) =>
      cn(
        'flex flex-col items-center justify-center p-2 text-xs font-medium transition-all duration-200 flex-1',
        isActive
          ? 'text-blue-500'
          : 'text-gray-400 hover:text-gray-200'
      )
    }
  >
    <item.icon className="h-5 w-5 mb-1" />
    <span className="text-[10px]">{item.name}</span>
  </NavLink>
);

export default function MobileLayout({ children }) {
  return (
    <div className="flex flex-col h-screen bg-gray-950 text-white overflow-hidden font-sans">
      {/* Top Header */}
      <header className="flex h-16 items-center px-4 border-b border-gray-800/50 bg-[#0F111A]/90 backdrop-blur-xl z-10 shrink-0 justify-between">
        <div className="flex items-center">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center mr-2">
             <Activity className="h-4 w-4 text-white" />
          </div>
          <span className="text-lg font-bold bg-gradient-to-r from-blue-400 to-indigo-500 text-transparent bg-clip-text">StockAI</span>
        </div>
        <div className="w-8 h-8 rounded-full bg-blue-900/40 flex items-center justify-center text-blue-400 font-bold text-xs border border-blue-500/20">
            AD
        </div>
      </header>
      
      {/* Main Content */}
      <main className="flex-1 overflow-y-auto bg-[#0a0a0f] p-4 text-sm pb-24">
        {children}
      </main>

      {/* Bottom Nav Bar */}
      <div className="fixed bottom-0 left-0 right-0 h-16 bg-[#0F111A]/95 backdrop-blur-xl border-t border-gray-800/50 z-50 flex items-center justify-between px-2 pb-safe">
        {navigation.map((item) => (
          <BottomNavItem key={item.name} item={item} />
        ))}
      </div>
    </div>
  );
}
