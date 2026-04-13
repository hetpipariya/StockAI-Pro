import { useStore } from '../store/useStore';

export const useDashboardData = () => {
  const balance = useStore((state) => state.balance);
  const todaysPnL = useStore((state) => state.todaysPnL);
  const winRate = useStore((state) => state.winRate);
  const activeTrades = useStore((state) => state.activeTrades);

  return { balance, todaysPnL, winRate, activeTrades };
};