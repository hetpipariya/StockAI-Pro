import React from 'react';
export const Badge = ({ children, variant = 'default', className }) => {
  const variants = {
    buy: 'bg-green-500/20 text-green-400',
    sell: 'bg-red-500/20 text-red-400',
    default: 'bg-gray-500/20 text-gray-400',
    info: 'bg-blue-500/20 text-blue-400',
  };

  return (
    <span
      className={`px-2 py-1 rounded text-xs font-bold ${
        variants[variant] || variants.default
      } ${className || ''}`}
    >
      {children}
    </span>
  );
};

export default Badge;