import React from 'react';
import PropTypes from 'prop-types';

/**
 * Reusable Loading Spinner component.
 * @param {Object} props
 * @param {'sm'|'lg'} [props.size='sm'] - Spinner size
 * @param {string} [props.text] - Optional text below the spinner
 */
export const Loader = ({ size = 'sm', text }) => {
  const diameter = size === 'lg' ? '40px' : '20px';
  const borderWidth = size === 'lg' ? '4px' : '2px';
  
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', justifyContent: 'center' }}>
      <div 
        className="stockai-spinner"
        style={{
          width: diameter,
          height: diameter,
          border: `${borderWidth} solid rgba(0, 255, 159, 0.2)`,
          borderTop: `${borderWidth} solid var(--primary, #00FF9F)`,
          borderRadius: '50%',
        }}
      />
      {text && <span style={{ color: 'var(--text-secondary, #a1a1aa)', fontSize: '12px', fontFamily: 'var(--font-family-base, sans-serif)' }}>{text}</span>}
      <style>
        {`
          @keyframes global-spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
          }
          .stockai-spinner {
            animation: global-spin 0.8s linear infinite;
          }
        `}
      </style>
    </div>
  );
};

Loader.propTypes = {
  size: PropTypes.oneOf(['sm', 'lg']),
  text: PropTypes.string,
};

export default Loader;
