import React from 'react';
import PropTypes from 'prop-types';

/**
 * Signal Badge component for BUY, SELL, HOLD states.
 * @param {Object} props
 * @param {'BUY'|'SELL'|'HOLD'} props.type - Signal type
 * @param {'sm'|'md'} [props.size='md'] - Visual size
 */
export const Badge = ({ type, size = 'md' }) => {
  let bg, color;
  switch (type) {
    case 'BUY':
      bg = '#00FF9F';
      color = '#06090E';
      break;
    case 'SELL':
      bg = '#FF4C4C';
      color = '#fff';
      break;
    case 'HOLD':
      bg = '#FFB347';
      color = '#06090E';
      break;
    default:
      bg = '#333';
      color = '#fff';
  }

  const isSmall = size === 'sm';
  
  return (
    <span style={{
      background: bg,
      color: color,
      fontSize: isSmall ? '11px' : '13px',
      padding: isSmall ? '2px 6px' : '4px 10px',
      borderRadius: '4px',
      fontWeight: '600',
      textTransform: 'uppercase',
      display: 'inline-block',
      fontFamily: 'var(--font-family-mono, monospace)',
      lineHeight: 1
    }}>
      {type}
    </span>
  );
};

Badge.propTypes = {
  type: PropTypes.oneOf(['BUY', 'SELL', 'HOLD']).isRequired,
  size: PropTypes.oneOf(['sm', 'md']),
};

export default Badge;
