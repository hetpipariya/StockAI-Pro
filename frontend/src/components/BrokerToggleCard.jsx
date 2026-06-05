import React, { useEffect, useState } from 'react';
import { Power, Shield, ShieldAlert, Sparkles, RefreshCw } from 'lucide-react';
import { apiClient } from '../api/client';

export default function BrokerToggleCard() {
  const [upstoxStatus, setUpstoxStatus] = useState({
    status: 'DISCONNECTED',
    token_valid: false,
    websocket_connected: false,
    last_auth_success: null,
    last_auth_failure: null,
    reconnect_attempts: 0,
  });
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const fetchStatus = async (isManual = false) => {
    if (isManual) setRefreshing(true);
    try {
      // Fetch status via apiClient which handles base path and Auth header automatically
      const res = await apiClient.get('/auth/broker/status');
      if (res) {
        setUpstoxStatus(res);
      }
    } catch (err) {
      console.error('Failed to fetch broker status:', err);
    } finally {
      if (isManual) setRefreshing(false);
    }
  };

  useEffect(() => {
    // Initial fetch
    fetchStatus();

    // Check url params for success / error messages
    const params = new URLSearchParams(window.location.search);
    if (params.get('broker_connected') === 'upstox') {
      // Clean query params
      const newUrl = window.location.pathname + window.location.hash;
      window.history.replaceState({}, document.title, newUrl);
    }

    // Set polling status every 3.5 seconds
    const interval = setInterval(() => {
      fetchStatus();
    }, 3500);

    return () => clearInterval(interval);
  }, []);

  const handleToggle = async () => {
    if (loading) return;
    setLoading(true);

    const isConnected = upstoxStatus.status === 'CONNECTED' || upstoxStatus.status === 'CONNECTING';

    if (isConnected) {
      // Disconnect
      try {
        await apiClient.post('/auth/disconnect/upstox');
        await fetchStatus();
      } catch (err) {
        console.error('Failed to disconnect Upstox:', err);
      } finally {
        setLoading(false);
      }
    } else {
      // Connect: Redirect to backend login handler
      const apiBase = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
      // Strip trailing slash and api/v1 suffix if present to redirect directly to auth login endpoint
      const baseHost = apiBase.replace(/\/api\/v1\/?$/, '').replace(/\/api\/?$/, '');
      window.location.href = `${baseHost}/login/upstox`;
    }
  };

  const getStatusDisplay = () => {
    switch (upstoxStatus.status) {
      case 'CONNECTED':
        return {
          label: 'Connected',
          badgeClass: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300 shadow-[0_0_12px_rgba(16,185,129,0.2)]',
          indicatorColor: 'bg-emerald-400 animate-pulse',
          description: 'Websocket connected & streaming market data',
        };
      case 'CONNECTING':
      case 'RECONNECTING':
        return {
          label: 'Reconnecting',
          badgeClass: 'border-amber-500/40 bg-amber-500/10 text-amber-300 shadow-[0_0_12px_rgba(245,158,11,0.2)]',
          indicatorColor: 'bg-amber-400 animate-bounce',
          description: 'Establishing broker link...',
        };
      case 'TOKEN_EXPIRED':
      case 'REAUTH_REQUIRED':
      case 'EXPIRED':
        return {
          label: 'Expired',
          badgeClass: 'border-orange-500/40 bg-orange-500/10 text-orange-300',
          indicatorColor: 'bg-orange-400',
          description: 'Session expired. Re-authentication required.',
        };
      default:
        return {
          label: 'Disconnected',
          badgeClass: 'border-rose-500/40 bg-rose-500/10 text-rose-300',
          indicatorColor: 'bg-rose-400',
          description: 'Not authenticated with Upstox.',
        };
    }
  };

  const display = getStatusDisplay();
  const upstoxActive = upstoxStatus.status === 'CONNECTED' || upstoxStatus.status === 'CONNECTING';

  return (
    <div className="rounded-2xl border border-white/10 bg-[#081628]/95 overflow-hidden shadow-2xl transition-all duration-300 hover:border-cyan-500/20">
      {/* Header section with gradient */}
      <div className="px-5 py-4 bg-gradient-to-r from-cyan-500/10 via-purple-500/5 to-transparent border-b border-white/10 flex items-center justify-between">
        <div>
          <h3 className="text-lg font-black text-white tracking-wide flex items-center gap-2">
            <Shield className="h-5 w-5 text-cyan-400" />
            Broker Connections
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">Centralized authorization and live session management</p>
        </div>
        <button
          onClick={() => fetchStatus(true)}
          disabled={refreshing}
          className="p-2 rounded-lg border border-white/10 bg-white/[0.02] hover:bg-white/[0.06] text-slate-400 transition"
          title="Refresh connection status"
        >
          <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin text-cyan-400' : ''}`} />
        </button>
      </div>

      <div className="p-5 space-y-4">
        {/* Upstox integration row */}
        <div className="rounded-xl border border-white/5 bg-white/[0.02] p-4 flex flex-col md:flex-row md:items-center justify-between gap-4 transition hover:bg-white/[0.04]">
          <div className="flex items-start gap-3">
            <div className={`h-11 w-11 rounded-xl border flex items-center justify-center transition-all duration-300 ${
              upstoxActive 
                ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300 shadow-[0_0_15px_rgba(16,185,129,0.15)]' 
                : 'border-white/10 bg-white/[0.03] text-slate-400'
            }`}>
              <Power className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-black text-white text-base">Upstox Pro</span>
                <span className={`px-2 py-0.5 rounded-full text-2xs font-bold border flex items-center gap-1.5 transition-all duration-300 ${display.badgeClass}`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${display.indicatorColor}`} />
                  {display.label}
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-1">{display.description}</p>
              
              {/* Token metadata details */}
              {upstoxStatus.last_auth_success && (
                <div className="mt-2 text-3xs text-slate-500 font-mono space-y-0.5">
                  <p>Last login: {new Date(upstoxStatus.last_auth_success).toLocaleString()}</p>
                  {upstoxStatus.reconnect_attempts > 0 && (
                    <p className="text-amber-400/80">Reconnect attempts: {upstoxStatus.reconnect_attempts}</p>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3 self-end md:self-auto">
            {/* Custom Premium Toggle Switch */}
            <button
              onClick={handleToggle}
              disabled={loading}
              className={`relative inline-flex h-6 w-11 items-center shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                upstoxActive ? 'bg-cyan-500 shadow-[0_0_10px_rgba(6,182,212,0.5)]' : 'bg-slate-700'
              } ${loading ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              <span
                className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-md ring-0 transition duration-200 ease-in-out ${
                  upstoxActive ? 'translate-x-5' : 'translate-x-0'
                }`}
              />
            </button>
          </div>
        </div>

        {/* Future Integrations section */}
        <div className="pt-2 border-t border-white/5">
          <p className="text-2xs uppercase tracking-widest text-slate-500 font-black mb-3">Inactive Adapters (Future Support)</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {['Angel One', 'Fyers', 'Zerodha'].map((broker) => (
              <div key={broker} className="rounded-lg border border-white/5 bg-white/[0.01] px-3 py-2 flex items-center justify-between opacity-50 cursor-not-allowed">
                <span className="text-xs font-semibold text-slate-400">{broker}</span>
                <span className="text-3xs uppercase px-1.5 py-0.5 border border-white/10 bg-white/5 rounded text-slate-500 font-bold">Planned</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
