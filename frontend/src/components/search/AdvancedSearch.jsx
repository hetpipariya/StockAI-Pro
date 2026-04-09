/**
 * Advanced Search Component
 * Sleek, sticky search bar with Cmd+K shortcut.
 * Debounced search results, global symbol discovery.
 * Production-ready with proper accessibility and animations.
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, ChevronRight, Zap } from 'lucide-react';
import { marketAPI } from '@/services/api/client';
import { useMarketStore } from '@/store/marketStore';
import clsx from 'clsx';

/**
 * Advanced Search Component
 * @component
 */
export function AdvancedSearch() {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const [symbolCatalog, setSymbolCatalog] = useState([]);

  const inputRef = useRef(null);
  const searchTimerRef = useRef(null);
  const { setSelectedSymbol } = useMarketStore();

  useEffect(() => {
    let active = true;

    const loadSymbols = async () => {
      try {
        const response = await marketAPI.getSymbols(250);
        const rows = Array.isArray(response?.data?.data) ? response.data.data : [];
        const normalized = rows
          .map((item) => {
            if (typeof item === 'string') {
              const symbol = item.trim().toUpperCase();
              return symbol ? { symbol, name: symbol } : null;
            }

            const symbol = String(item?.symbol || '').trim().toUpperCase();
            if (!symbol) return null;
            return {
              symbol,
              name: String(item?.name || symbol),
            };
          })
          .filter(Boolean);

        if (active) {
          setSymbolCatalog(normalized);
        }
      } catch (_) {
        if (active) {
          setSymbolCatalog([]);
        }
      }
    };

    loadSymbols();

    return () => {
      active = false;
    };
  }, []);

  /**
   * Perform debounced search
   * Only triggers API call if query hasn't changed for 300ms
   */
  const performSearch = useCallback((searchQuery) => {
    // Clear existing timer
    if (searchTimerRef.current) {
      clearTimeout(searchTimerRef.current);
    }

    if (!searchQuery.trim()) {
      setResults([]);
      setIsSearching(false);
      return;
    }

    setIsSearching(true);

    // Debounce: 300ms delay before search
    searchTimerRef.current = setTimeout(() => {
      const q = searchQuery.trim().toUpperCase();
      const searchResults = symbolCatalog
        .filter((stock) => {
          const symbol = String(stock.symbol || '').toUpperCase();
          const name = String(stock.name || '').toUpperCase();
          return symbol.includes(q) || name.includes(q);
        })
        .slice(0, 20);
      setResults(searchResults);
      setHighlightedIndex(0);
      setIsSearching(false);
    }, 300);
  }, [symbolCatalog]);

  /**
   * Handle search input change
   */
  const handleInputChange = (e) => {
    const value = e.target.value.toUpperCase();
    setQuery(value);
    performSearch(value);
  };

  /**
   * Handle symbol selection
   */
  const handleSelectSymbol = (symbol) => {
    setSelectedSymbol(symbol);
    setIsOpen(false);
    setQuery('');
    setResults([]);
  };

  /**
   * Keyboard navigation
   */
  const handleKeyDown = (e) => {
    if (!isOpen && e.key === 'k' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      setIsOpen(true);
      setTimeout(() => inputRef.current?.focus(), 50);
      return;
    }

    if (!isOpen) return;

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setHighlightedIndex((prev) =>
          prev < results.length - 1 ? prev + 1 : prev
        );
        break;

      case 'ArrowUp':
        e.preventDefault();
        setHighlightedIndex((prev) => (prev > 0 ? prev - 1 : 0));
        break;

      case 'Enter':
        e.preventDefault();
        if (results[highlightedIndex]) {
          handleSelectSymbol(results[highlightedIndex].symbol);
        }
        break;

      case 'Escape':
        e.preventDefault();
        setIsOpen(false);
        break;

      default:
        break;
    }
  };

  // Listen for Cmd+K globally
  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, results, highlightedIndex]);

  return (
    <>
      {/* Search Trigger Button */}
      <motion.button
        onClick={() => {
          setIsOpen(true);
          setTimeout(() => inputRef.current?.focus(), 50);
        }}
        className="relative w-full max-w-md px-4 py-2.5 bg-gradient-to-r from-slate-800/40 to-slate-900/40 border border-blue-500/20 rounded-lg hover:border-blue-500/50 transition-colors group"
        whileHover={{ borderColor: 'rgba(59, 130, 246, 0.5)' }}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 text-slate-400">
            <Search size={18} className="text-blue-400/60" />
            <span className="text-sm">Search symbols...</span>
          </div>
          <span className="text-xs px-2 py-1 bg-slate-700/50 rounded text-slate-300 group-hover:bg-slate-600 transition-colors">
            ⌘K
          </span>
        </div>
      </motion.button>

      {/* Search Modal */}
      <AnimatePresence>
        {isOpen && (
          <>
            {/* Backdrop */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setIsOpen(false)}
              className="fixed inset-0 bg-black/40 backdrop-blur-sm z-40"
            />

            {/* Search Dialog */}
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: -20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: -20 }}
              className="fixed left-1/2 top-20 -translate-x-1/2 w-full max-w-2xl z-50"
            >
              <div className="bg-gradient-to-b from-slate-800 to-slate-900 border border-blue-500/20 rounded-xl shadow-2xl overflow-hidden backdrop-blur">
                {/* Search Input */}
                <div className="px-6 py-4 border-b border-blue-500/10">
                  <div className="flex items-center gap-3">
                    <Search size={20} className="text-blue-400" />
                    <input
                      ref={inputRef}
                      type="text"
                      value={query}
                      onChange={handleInputChange}
                      placeholder="Search by symbol or company name..."
                      className="flex-1 bg-transparent text-white placeholder-slate-500 outline-none text-lg"
                      autoFocus
                    />
                  </div>
                </div>

                {/* Results */}
                <div className="max-h-96 overflow-y-auto">
                  {isSearching && (
                    <div className="px-6 py-8 text-center">
                      <div className="inline-block">
                        <div className="w-8 h-8 border-2 border-blue-400/30 border-t-blue-400 rounded-full animate-spin" />
                      </div>
                      <p className="text-slate-400 mt-3">Searching...</p>
                    </div>
                  )}

                  {!isSearching && results.length === 0 && query && (
                    <div className="px-6 py-8 text-center">
                      <Zap size={32} className="mx-auto text-slate-600 mb-3" />
                      <p className="text-slate-400">No results found for "{query}"</p>
                    </div>
                  )}

                  {!isSearching && results.length > 0 && (
                    <div className="py-2 px-2">
                      {results.map((stock, index) => (
                        <motion.button
                          key={stock.symbol}
                          onClick={() => handleSelectSymbol(stock.symbol)}
                          className={clsx(
                            'w-full px-4 py-3 rounded-lg text-left transition-all flex items-center justify-between group',
                            highlightedIndex === index
                              ? 'bg-blue-500/20 border border-blue-400/50'
                              : 'hover:bg-slate-700/40 border border-transparent'
                          )}
                          whileHover={{ x: 4 }}
                        >
                          <div>
                            <div className="font-semibold text-white group-hover:text-blue-300 transition-colors">
                              {stock.symbol}
                            </div>
                            <div className="text-xs text-slate-400 group-hover:text-slate-300">
                              {stock.name}
                            </div>
                          </div>
                          <ChevronRight
                            size={18}
                            className="text-slate-500 group-hover:text-blue-400 transition-colors"
                          />
                        </motion.button>
                      ))}
                    </div>
                  )}

                  {!isSearching && !query && (
                    <div className="px-6 py-8">
                      <p className="text-xs text-slate-500 mb-4 uppercase tracking-wider">
                        Popular
                      </p>
                      <div className="space-y-2">
                        {['RELIANCE', 'TCS', 'INFY', 'HDFCBANK'].map(
                          (symbol) => (
                            <button
                              key={symbol}
                              onClick={() => handleSelectSymbol(symbol)}
                              className="w-full px-4 py-2 text-left text-sm text-slate-300 hover:text-blue-300 hover:bg-slate-700/30 rounded transition-colors"
                            >
                              → {symbol}
                            </button>
                          )
                        )}
                      </div>
                    </div>
                  )}
                </div>

                {/* Footer */}
                <div className="px-6 py-3 border-t border-blue-500/10 bg-slate-900/50 text-xs text-slate-500 flex gap-4">
                  <span>↑↓ Navigate</span>
                  <span>⏎ Select</span>
                  <span>⎋ Close</span>
                </div>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  );
}

export default AdvancedSearch;
