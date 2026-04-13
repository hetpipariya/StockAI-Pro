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
          ? 'bg-blue-600/10 text-blue-500 shadow-[inset_4px_0_0_0_rgba(59,130,246,1)]'
          : 'text-gray-400 hover:bg-gray-800/50 hover:text-gray-200'
      )
    }
    title={item.name}
  >
    <item.icon className="h-6 w-6 flex-shrink-0" />
  </NavLink>
);

export default function TabletLayout({ children }) {
  return (
    <div className="flex h-screen bg-gray-950 text-white overflow-hidden font-sans">
      {/* Narrow Sidebar */}
      <div className="w-24 flex flex-col bg-[#0F111A] border-r border-gray-800/50 backdrop-blur-xl z-20 items-center">
        <div className="flex h-20 shrink-0 items-center justify-center border-b border-gray-800/50 w-full mb-4">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-blue-500/20">
             <Activity className="h-6 w-6 text-white" />
          </div>
        </div>
        <div className="flex flex-1 flex-col overflow-y-auto w-full px-3 pb-4 scrollbar-hide items-center">
          <nav className="flex-1 w-full">
            {navigation.map((item) => (
              <SidebarItem key={item.name} item={item} />
            ))}
          </nav>
        </div>
        <div className="p-4 border-t border-gray-800/50 w-full flex justify-center">
           <div className="w-10 h-10 rounded-full bg-blue-900/40 flex items-center justify-center text-blue-400 font-bold border border-blue-500/20 cursor-pointer">
              AD
           </div>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex flex-1 flex-col overflow-hidden relative">
        {/* Top Header */}
        <header className="flex h-20 items-center px-6 border-b border-gray-800/50 bg-[#0F111A]/80 backdrop-blur-xl z-10 sticky top-0 justify-between">
          <h1 className="text-xl font-semibold text-gray-100 tracking-tight">StockAI Pro</h1>
          <div className="flex items-center space-x-4">
             <div className="px-3 py-1.5 rounded-full bg-green-500/10 text-green-400 text-xs font-medium border border-green-500/20 flex items-center">
               <span className="w-2 h-2 rounded-full bg-green-500 mr-2 animate-pulse shadow-[0_0_8px_rgba(34,197,94,0.8)]"></span>
               Live
             </div>
          </div>
        </header>
        
        {/* Page Content */}
        <main className="flex-1 overflow-y-auto bg-[#0a0a0f] p-6 text-sm">
          <div className="mx-auto max-w-7xl">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
