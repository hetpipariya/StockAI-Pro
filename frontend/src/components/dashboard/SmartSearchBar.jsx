import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { History, Mic, Search, TrendingUp } from 'lucide-react';

import { searchMarketSymbols } from '../../lib/api';

const RECENT_KEY = 'stockai_recent_symbols';
const FALLBACK_TRENDING_SYMBOLS = ['RELIANCE', 'HDFCBANK', 'ICICIBANK', 'TCS', 'INFY'];

const normalize = (text) => String(text || '').toLowerCase().replace(/[^a-z0-9]/g, '');

const toNumber = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const formatPrice = (value) => {
  const amount = toNumber(value);
  return amount === null ? '--' : `₹ ${amount.toFixed(2)}`;
};

const levenshtein = (left, right) => {
  if (!left.length) return right.length;
  if (!right.length) return left.length;

  const matrix = Array.from({ length: left.length + 1 }, () => Array(right.length + 1).fill(0));
  for (let i = 0; i <= left.length; i += 1) matrix[i][0] = i;
  for (let j = 0; j <= right.length; j += 1) matrix[0][j] = j;

  for (let i = 1; i <= left.length; i += 1) {
    for (let j = 1; j <= right.length; j += 1) {
      const cost = left[i - 1] === right[j - 1] ? 0 : 1;
      matrix[i][j] = Math.min(
        matrix[i - 1][j] + 1,
        matrix[i][j - 1] + 1,
        matrix[i - 1][j - 1] + cost,
      );
    }
  }

  return matrix[left.length][right.length];
};

const computeScore = (stock, query) => {
  const q = normalize(query);
  if (!q) return 0;

  const symbol = normalize(stock.symbol);
  const name = normalize(stock.name);
  const aliases = Array.isArray(stock.aliases) ? stock.aliases.map(normalize) : [];

  let score = -1;

  if (symbol === q) score = Math.max(score, 100);
  if (symbol.startsWith(q)) score = Math.max(score, 90);
  if (symbol.includes(q)) score = Math.max(score, 80);

  if (name.startsWith(q)) score = Math.max(score, 72);
  if (name.includes(q)) score = Math.max(score, 64);

  if (aliases.some((alias) => alias === q)) score = Math.max(score, 86);
  if (aliases.some((alias) => alias.includes(q))) score = Math.max(score, 70);

  if (q.length >= 3) {
    const targets = [symbol, name, ...aliases, ...name.split(/\s+/).filter(Boolean)];
    let minDistance = Infinity;

    targets.forEach((target) => {
      if (!target) return;
      const distance = levenshtein(q, target.slice(0, Math.max(q.length, 3)));
      minDistance = Math.min(minDistance, distance);
    });

    if (minDistance <= 2) {
      score = Math.max(score, 58 - (minDistance * 12));
    }
  }

  return score;
};

const readRecentSymbols = () => {
  try {
    const parsed = JSON.parse(localStorage.getItem(RECENT_KEY) || '[]');
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((value) => typeof value === 'string');
  } catch {
    return [];
  }
};

const saveRecentSymbols = (symbols) => {
  localStorage.setItem(RECENT_KEY, JSON.stringify(symbols.slice(0, 5)));
};

const mergeUnique = (stocks) => {
  const map = new Map();
  stocks.forEach((stock) => {
    if (!stock?.symbol) return;
    if (!map.has(stock.symbol)) map.set(stock.symbol, stock);
  });
  return [...map.values()];
};

const SmartSearchBar = React.memo(function SmartSearchBar({
  selectedSymbol,
  onSelectSymbol,
  priceBySymbol = {},
  catalog = [],
  trendingSymbols = [],
}) {
  const [query, setQuery] = useState(selectedSymbol || 'RELIANCE');
  const [debouncedQuery, setDebouncedQuery] = useState(selectedSymbol || 'RELIANCE');
  const [isOpen, setIsOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [recentSymbols, setRecentSymbols] = useState(() => readRecentSymbols());
  const [remoteMatches, setRemoteMatches] = useState([]);
  const [remoteLoading, setRemoteLoading] = useState(false);

  const rootRef = useRef(null);
  const liveQuery = query.trim();

  useEffect(() => {
    setQuery(selectedSymbol || '');
  }, [selectedSymbol]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(query.trim());
    }, 300);

    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    let cancelled = false;

    const run = async () => {
      if (!debouncedQuery || debouncedQuery.length < 2) {
        setRemoteMatches([]);
        setRemoteLoading(false);
        return;
      }

      setRemoteLoading(true);
      try {
        const rows = await searchMarketSymbols(debouncedQuery, 30);
        if (cancelled) return;
        setRemoteMatches(Array.isArray(rows) ? rows : []);
      } catch {
        if (cancelled) return;
        setRemoteMatches([]);
      } finally {
        if (!cancelled) {
          setRemoteLoading(false);
        }
      }
    };

    run();
    return () => {
      cancelled = true;
    };
  }, [debouncedQuery]);

  useEffect(() => {
    const onOutsideClick = (event) => {
      if (!rootRef.current?.contains(event.target)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', onOutsideClick);
    return () => document.removeEventListener('mousedown', onOutsideClick);
  }, []);

  const normalizedCatalog = useMemo(() => {
    const rows = Array.isArray(catalog) ? catalog : [];
    const map = new Map();

    rows.forEach((item) => {
      if (!item) return;
      const symbol = String(item.symbol || '').trim().toUpperCase();
      if (!symbol || map.has(symbol)) return;
      map.set(symbol, {
        symbol,
        name: String(item.name || symbol),
        aliases: Array.isArray(item.aliases)
          ? item.aliases.filter((value) => typeof value === 'string')
          : [],
      });
    });

    return [...map.values()];
  }, [catalog]);

  const catalogBySymbol = useMemo(() => {
    return new Map(normalizedCatalog.map((stock) => [stock.symbol, stock]));
  }, [normalizedCatalog]);

  const searchableCatalog = useMemo(() => {
    return mergeUnique([...normalizedCatalog, ...(Array.isArray(remoteMatches) ? remoteMatches : [])]);
  }, [normalizedCatalog, remoteMatches]);

  const trendingStocks = useMemo(
    () => {
      const sourceSymbols = Array.isArray(trendingSymbols) && trendingSymbols.length
        ? trendingSymbols
        : FALLBACK_TRENDING_SYMBOLS;

      const resolved = sourceSymbols
        .map((symbol) => {
          const normalized = String(symbol || '').trim().toUpperCase();
          if (!normalized) return null;
          return catalogBySymbol.get(normalized) || {
            symbol: normalized,
            name: normalized,
            aliases: [],
          };
        })
        .filter(Boolean);

      return resolved.slice(0, 5);
    },
    [catalogBySymbol, trendingSymbols],
  );

  const recentStocks = useMemo(
    () => {
      return recentSymbols
        .map((symbol) => {
          const normalized = String(symbol || '').trim().toUpperCase();
          if (!normalized) return null;
          return catalogBySymbol.get(normalized) || {
            symbol: normalized,
            name: normalized,
            aliases: [],
          };
        })
        .filter(Boolean);
    },
    [catalogBySymbol, recentSymbols],
  );

  const suggestions = useMemo(() => {
    if (!liveQuery) return [];

    if (!searchableCatalog.length) return [];

    const ranked = searchableCatalog
      .map((stock) => ({ stock, score: computeScore(stock, liveQuery) }))
      .filter((entry) => entry.score >= 0)
      .sort((left, right) => right.score - left.score)
      .slice(0, 8)
      .map((entry) => entry.stock);

    return ranked;
  }, [liveQuery, searchableCatalog]);

  const keyboardRows = useMemo(() => {
    if (liveQuery) return suggestions;
    return mergeUnique([...recentStocks, ...trendingStocks]);
  }, [liveQuery, recentStocks, suggestions, trendingStocks]);

  const handleSelect = (stock) => {
    if (!stock?.symbol) return;

    onSelectSymbol(stock.symbol, stock);
    setQuery(stock.symbol);
    setDebouncedQuery(stock.symbol);
    setIsOpen(false);

    const nextRecent = [stock.symbol, ...recentSymbols.filter((symbol) => symbol !== stock.symbol)].slice(0, 5);
    setRecentSymbols(nextRecent);
    saveRecentSymbols(nextRecent);
  };

  const onKeyDown = (event) => {
    if (!isOpen) return;

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveIndex((current) => Math.min(current + 1, Math.max(keyboardRows.length - 1, 0)));
      return;
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex((current) => Math.max(current - 1, 0));
      return;
    }

    if (event.key === 'Enter') {
      event.preventDefault();

      const selected = keyboardRows[activeIndex] || keyboardRows[0];
      if (selected) {
        handleSelect(selected);
        return;
      }

      const directSymbol = liveQuery.toUpperCase();
      if (directSymbol) {
        const fallback = catalogBySymbol.get(directSymbol) || {
          symbol: directSymbol,
          name: directSymbol,
          aliases: [],
        };
        handleSelect(fallback);
      }
      return;
    }

    if (event.key === 'Escape') {
      setIsOpen(false);
    }
  };

  useEffect(() => {
    setActiveIndex(0);
  }, [liveQuery, isOpen]);

  const displayPrice = (stock) => {
    const livePrice = priceBySymbol[stock.symbol];
    return formatPrice(livePrice);
  };

  return (
    <div ref={rootRef} className="relative w-full" onKeyDown={onKeyDown}>
      <div className="relative">
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-stockai-muted w-4 h-4" />
        <input
          type="text"
          value={query}
          onFocus={() => setIsOpen(true)}
          onChange={(event) => {
            setQuery(event.target.value);
            setIsOpen(true);
          }}
          placeholder="Search symbol, company, alias (rel / reliance / relaince)"
          className="w-full bg-stockai-bg border border-white/10 rounded-full py-2.5 pl-11 pr-12 text-sm focus:outline-none focus:border-stockai-neon focus:ring-1 focus:ring-stockai-neon/40 transition-all"
        />
        <button
          type="button"
          className="absolute right-3 top-1/2 -translate-y-1/2 text-stockai-muted hover:text-stockai-neon transition-colors"
          aria-label="Voice search"
          title="Voice search (UI only)"
        >
          <Mic className="w-4 h-4" />
        </button>
      </div>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            transition={{ duration: 0.2 }}
            className="absolute z-50 mt-3 w-full rounded-2xl border border-white/10 bg-[#0A1119]/95 backdrop-blur-xl shadow-[0_16px_40px_rgba(0,0,0,0.55)] overflow-hidden"
          >
            <div className="max-h-[360px] overflow-y-auto p-2">
              {liveQuery ? (
                <>
                  {suggestions.length === 0 ? (
                    <div className="px-4 py-8 text-center text-stockai-muted text-sm">
                      No stock found. Try symbol/name/alias.
                    </div>
                  ) : (
                    suggestions.map((stock, index) => (
                      <button
                        type="button"
                        key={stock.symbol}
                        onClick={() => handleSelect(stock)}
                        className={`w-full px-3 py-3 rounded-xl text-left border transition-all ${
                          activeIndex === index
                            ? 'border-stockai-neon/60 bg-stockai-neon/10'
                            : 'border-transparent hover:border-white/10 hover:bg-white/5'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <p className="text-sm font-bold text-white">{stock.name}</p>
                            <p className="text-xs text-stockai-muted font-mono">{stock.symbol}</p>
                          </div>
                          <p className="text-sm font-mono text-stockai-neon">{displayPrice(stock)}</p>
                        </div>
                      </button>
                    ))
                  )}
                </>
              ) : (
                <>
                  <div className="px-2 py-2">
                    <p className="px-2 pb-2 text-[11px] uppercase tracking-widest text-stockai-muted flex items-center gap-2">
                      <TrendingUp className="w-3 h-3" /> Trending Stocks
                    </p>
                    <div className="space-y-1">
                      {trendingStocks.map((stock, index) => (
                        <button
                          type="button"
                          key={stock.symbol}
                          onClick={() => handleSelect(stock)}
                          className={`w-full px-3 py-3 rounded-xl text-left border transition-all ${
                            activeIndex === index
                              ? 'border-stockai-neon/60 bg-stockai-neon/10'
                              : 'border-transparent hover:border-white/10 hover:bg-white/5'
                          }`}
                        >
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <p className="text-sm font-bold text-white">{stock.name}</p>
                              <p className="text-xs text-stockai-muted font-mono">{stock.symbol}</p>
                            </div>
                            <p className="text-sm font-mono text-stockai-neon">{displayPrice(stock)}</p>
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>

                  {recentStocks.length > 0 && (
                    <div className="px-2 pt-1 pb-2 border-t border-white/5">
                      <p className="px-2 py-2 text-[11px] uppercase tracking-widest text-stockai-muted flex items-center gap-2">
                        <History className="w-3 h-3" /> Recent Search
                      </p>
                      <div className="space-y-1">
                        {recentStocks.map((stock, index) => (
                          <button
                            type="button"
                            key={`recent-${stock.symbol}`}
                            onClick={() => handleSelect(stock)}
                            className={`w-full px-3 py-3 rounded-xl text-left border transition-all ${
                              activeIndex === index + trendingStocks.length
                                ? 'border-stockai-neon/60 bg-stockai-neon/10'
                                : 'border-transparent hover:border-white/10 hover:bg-white/5'
                            }`}
                          >
                            <div className="flex items-center justify-between gap-3">
                              <div>
                                <p className="text-sm font-bold text-white">{stock.name}</p>
                                <p className="text-xs text-stockai-muted font-mono">{stock.symbol}</p>
                              </div>
                              <p className="text-sm font-mono text-stockai-neon">{displayPrice(stock)}</p>
                            </div>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}

              {liveQuery && remoteLoading && (
                <div className="px-4 pb-3 text-xs text-stockai-muted">Searching live symbols...</div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

export default SmartSearchBar;
