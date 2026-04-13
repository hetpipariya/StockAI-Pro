import React from 'react';
import { Card } from '../ui';

const KpiCards = ({ kpidata }) => {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
      {kpidata.map(stat => (
        <Card key={stat.label}>
          <div className="flex justify-between items-start mb-4">
            <h3 className="text-gray-400 font-medium text-sm">{stat.label}</h3>
          </div>
          <div className="text-lg sm:text-2xl md:text-3xl font-black text-white">{stat.value}</div>
        </Card>
      ))}
    </div>
  );
};
export default KpiCards;