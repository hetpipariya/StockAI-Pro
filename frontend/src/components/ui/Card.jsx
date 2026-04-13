import React from 'react';
export const Card = ({ children, className, ...props }) => (
  <div
    className={`bg-[#111424] border border-gray-800/80 p-6 rounded-2xl shadow-xl ${
      className || ''
    }`}
    {...props}
  >
    {children}
  </div>
);

export default Card;