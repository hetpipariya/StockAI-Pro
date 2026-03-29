import React from 'react';

export const SkeletonCard = ({ width = '100%', height = '150px' }) => {
  return (
    <div style={{
      width,
      height,
      background: 'linear-gradient(90deg, #0C1118 0%, #1A2332 50%, #0C1118 100%)',
      backgroundSize: '200% 100%',
      animation: 'shimmer 1.5s infinite linear',
      borderRadius: '8px'
    }} />
  );
};

export const SkeletonText = ({ width = '100%', height = '20px' }) => {
  return (
    <div style={{
      width,
      height,
      background: 'linear-gradient(90deg, #0C1118 0%, #1A2332 50%, #0C1118 100%)',
      backgroundSize: '200% 100%',
      animation: 'shimmer 1.5s infinite linear',
      borderRadius: '4px'
    }} />
  );
};
