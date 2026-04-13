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
        'group flex items-center px-4 py-3 text-sm font-medium rounded-lg transition-all duration-200',
        isActive
          ? 'bg-blue-600/10 text-blue-500 shadow-[inset_4px_0_0_0_rgba(59,130,246,1)]'
          : 'text-gray-400 hover:bg-gray-800/50 hover:text-gray-200'
      )
    }
  >
    <item.icon className="mr-3 h-5 w-5 flex-shrink-0" />
    {item.name}
  </NavLink>
);

export default function DesktopLayout({ children }) {
  return (
    <div className="flex h-screen bg-gray-950 text-white overflow-hidden font-sans">
      {/* Sidebar */}
      <div className="hidden w-72 md:flex flex-col bg-[#0F111A] border-r border-gray-800/50 backdrop-blur-xl z-20">
        <div className="flex h-20 shrink-0 items-center px-6 border-b border-gray-800/50">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center mr-3 shadow-lg shadow-blue-500/20">
             <Activity className="h-6 w-6 text-white" />
          </div>
          <span className="text-xl font-bold bg-gradient-to-r from-blue-400 to-indigo-500 text-transparent bg-clip-text tracking-tight">StockAI Pro</span>
        </div>
        <div className="flex flex-1 flex-col overflow-y-auto pt-6 pb-4 scrollbar-hide">
          <nav className="flex-1 space-y-2 px-4">
            {navigation.map((item) => (
              <SidebarItem key={item.name} item={item} />
            ))}
          </nav>
        </div>
        <div className="p-6 border-t border-gray-800/50">
           <div className="flex items-center space-x-3 bg-gray-900/50 p-3 rounded-xl border border-gray-800/50 hover:bg-gray-800/50 transition-colors cursor-pointer">
             <div className="w-10 h-10 rounded-full bg-blue-900/40 flex items-center justify-center text-blue-400 font-bold border border-blue-500/20">
                AD
             </div>
             <div className="flex-1 min-w-0">
               <p className="text-sm font-semibold text-gray-200 truncate">Admin User</p>
               <p className="text-xs text-gray-500 truncate">Pro Plan</p>
             </div>
           </div>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex flex-1 flex-col overflow-hidden relative">
        {/* Top Header */}
        <header className="flex h-20 items-center px-8 border-b border-gray-800/50 bg-[#0F111A]/80 backdrop-blur-xl z-10 sticky top-0 justify-between">
          <div className="flex items-center">
            <h1 className="text-xl font-semibold text-gray-100 tracking-tight">Dashboard Overview</h1>
          </div>
          <div className="flex items-center space-x-4">
             <div className="px-4 py-1.5 rounded-full bg-green-500/10 text-green-400 text-sm font-medium border border-green-500/20 flex items-center shadow-[0_0_15px_rgba(34,197,94,0.1)]">
               <span className="w-2 h-2 rounded-full bg-green-500 mr-2 animate-pulse shadow-[0_0_8px_rgba(34,197,94,0.8)]"></span>
               System Online
             </div>
             <button className="px-4 py-2 rounded-lg bg-gray-800/50 text-gray-300 text-sm font-medium border border-gray-700 hover:bg-gray-700 transition-colors flex items-center">
               <span>₹ INR</span>
             </button>
          </div>
        </header>
        
        {/* Page Content */}
        <main className="flex-1 overflow-y-auto bg-[#0a0a0f] p-8">
          <div className="mx-auto max-w-7xl">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
