import { create } from 'zustand';
import { PriceData } from './types';

interface PriceStoreState {
  prices: Map<string, PriceData>;
  updatePrice: (symbol: string, priceData: PriceData) => void;
  updatePrices: (pricesMap: Map<string, PriceData>) => void;
  resetPrices: () => void;
  getPrice: (symbol: string) => PriceData | undefined;
  getPrices: () => PriceData[];
}

export const usePriceStore = create<PriceStoreState>((set, get) => ({
  prices: new Map(),

  updatePrice: (symbol, priceData) => {
    const newPrices = new Map(get().prices);
    newPrices.set(symbol, priceData);
    set({ prices: newPrices });
  },

  updatePrices: (pricesMap) => {
    const newPrices = new Map(get().prices);
    pricesMap.forEach((price, symbol) => {
      newPrices.set(symbol, price);
    });
    set({ prices: newPrices });
  },

  resetPrices: () => set({ prices: new Map() }),

  getPrice: (symbol) => get().prices.get(symbol),

  getPrices: () => Array.from(get().prices.values()),
}));
