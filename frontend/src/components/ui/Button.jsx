import React from 'react';
import PropTypes from 'prop-types';

/**
 * Reusable Button component for the StockAI-Pro UI.
 * @param {Object} props
 * @param {string} props.label - Text to display on the button
 * @param {function} props.onClick - Click handler
 * @param {'primary'|'ghost'|'danger'} [props.variant='primary'] - Visual style variant
 * @param {boolean} [props.disabled=false] - Disabled state
 */
export const Button = ({ label, onClick, variant = 'primary', disabled = false }) => {
  const baseStyle = {
    padding: '8px 16px',
    borderRadius: '4px',
    border: 'none',
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.5 : 1,
    fontFamily: 'var(--font-family-base, sans-serif)',
    fontSize: '14px',
    transition: 'filter 0.2s ease, opacity 0.2s ease',
    outline: 'none',
    textAlign: 'center',
  };

  let variantStyle = {};
  switch (variant) {
    case 'primary':
      variantStyle = {
        background: 'var(--primary, #00FF9F)',
        color: '#06090E',
        fontWeight: 'bold',
      };
      break;
    case 'ghost':
      variantStyle = {
        background: 'transparent',
        border: '1px solid var(--border, #1A2332)',
        color: '#fff',
      };
      break;
    case 'danger':
      variantStyle = {
        background: '#FF4C4C',
        color: '#fff',
        fontWeight: 'bold',
        border: 'none'
      };
      break;
    default:
      break;
  }

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{ ...baseStyle, ...variantStyle }}
      onMouseEnter={(e) => { if (!disabled) e.target.style.filter = 'brightness(1.15)'; }}
      onMouseLeave={(e) => { if (!disabled) e.target.style.filter = 'brightness(1)'; }}
    >
      {label}
    </button>
  );
};

Button.propTypes = {
  label: PropTypes.string.isRequired,
  onClick: PropTypes.func.isRequired,
  variant: PropTypes.oneOf(['primary', 'ghost', 'danger']),
  disabled: PropTypes.bool,
};

export default Button;
