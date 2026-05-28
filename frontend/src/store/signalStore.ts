import { create } from 'zustand';
import { Signal, SignalFilter, SignalAction } from './types';

interface SignalStoreState {
  signals: Signal[];
  latestSignals: Signal[];
  filter: SignalFilter;
  setSignals: (signals: Signal[]) => void;
  addSignal: (signal: Signal) => void;
  setFilter: (filter: SignalFilter) => void;
  clearSignals: () => void;
  getFilteredSignals: () => Signal[];
}

export const useSignalStore = create<SignalStoreState>((set, get) => ({
  signals: [],
  latestSignals: [],
  filter: 'all',

  setSignals: (signals) => {
    set({
      signals,
      latestSignals: signals.slice(0, 10),
    });
  },

  addSignal: (signal) => {
    const currentSignals = get().signals;
    const newSignals = [signal, ...currentSignals];
    set({
      signals: newSignals,
      latestSignals: newSignals.slice(0, 10),
    });
  },

  setFilter: (filter) => set({ filter }),

  clearSignals: () => set({
    signals: [],
    latestSignals: [],
  }),

  getFilteredSignals: () => {
    const state = get();
    if (state.filter === 'all') return state.signals;
    return state.signals.filter(
      (signal) => signal.action.toLowerCase() === state.filter.toLowerCase()
    );
  },
}));
