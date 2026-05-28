import React from 'react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

const EquityChart = ({ data = [] }) => {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data}>
        <defs>
          <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.4} />
            <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" vertical={false} />
        <XAxis dataKey="time" stroke="#4b5563" />
        <YAxis stroke="#4b5563" />
        <Tooltip contentStyle={{ backgroundColor: '#0f1222', borderRadius: '8px' }} />
        <Area type="monotone" dataKey="value" stroke="#3b82f6" fill="url(#colorValue)" />
      </AreaChart>
    </ResponsiveContainer>
  );
};
export default EquityChart;