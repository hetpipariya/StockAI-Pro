import React from 'react';
import PropTypes from 'prop-types';

/**
 * Reusable Card container component.
 * @param {Object} props
 * @param {React.ReactNode} props.children - Content inside the card
 * @param {string} [props.className] - Optional extra CSS classes
 * @param {Object} [props.style] - Optional extra inline styles
 */
export const Card = ({ children, className = '', style = {} }) => {
  return (
    <div
      className={className}
      style={{
        background: 'var(--card, #0C1118)',
        border: '1px solid var(--border, #1A2332)',
        borderRadius: '8px',
        padding: '16px',
        ...style
      }}
    >
      {children}
    </div>
  );
};

Card.propTypes = {
  children: PropTypes.node.isRequired,
  className: PropTypes.string,
  style: PropTypes.object,
};

export default Card;
