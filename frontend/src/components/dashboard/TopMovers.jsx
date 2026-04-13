import React from 'react';
import { Card, Badge } from '../ui';

const TopMovers = () => {
  const mockMovers = [
    { symbol: 'RELIANCE', change: '+2.4%', up: true },
    { symbol: 'HDFCBANK', change: '-1.2%', up: false },
    { symbol: 'TCS', change: '+0.8%', up: true }
  ];

  return (
    <Card>
      <h3 className="text-xl font-bold mb-4 text-white">Top Movers</h3>
      <div className="space-y-3">
        {mockMovers.map(mover => (
          <div key={mover.symbol} className="flex justify-between items-center p-3 bg-gray-800/30 rounded-lg">
            <span className="font-bold text-white">{mover.symbol}</span>
            <Badge variant={mover.up ? 'buy' : 'sell'}>{mover.change}</Badge>
          </div>
        ))}
      </div>
    </Card>
  );
};
export default TopMovers;