import Navbar from '../components/features/Navbar';
import WatchlistPanel from '../components/features/WatchlistPanel';
import ChartPanel from '../components/features/ChartPanel';
import SignalCard from '../components/features/SignalCard';

export default function DesktopLayout() {
  return (
    <div style={{ height: "100vh", width: "100%", display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-app)" }}>
      <Navbar />
      <div style={{ 
        display: "grid", 
        gridTemplateColumns: "20fr 55fr 25fr", 
        gap: "12px",
        padding: "16px",
        flex: 1, 
        overflow: "hidden" 
      }}>
        {/* Left: Watchlist */}
        <div style={{ background: "var(--bg-panel)", borderRadius: "8px", overflow: "hidden", border: "1px solid var(--border)" }}>
          <WatchlistPanel />
        </div>
        {/* Center: Chart */}
        <div style={{ background: "var(--bg-panel)", borderRadius: "8px", overflow: "hidden", border: "1px solid var(--border)" }}>
          <ChartPanel />
        </div>
        {/* Right: Signal Panel */}
        <div style={{ overflow: "hidden" }}>
          <SignalCard />
        </div>
      </div>
    </div>
  );
}
