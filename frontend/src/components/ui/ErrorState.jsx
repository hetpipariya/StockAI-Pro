import React from 'react';

export default function ErrorState({ title = 'Something went wrong', message, onRetry }) {
  return (
    <div
      style={{
        border: '1px solid rgba(255, 76, 76, 0.35)',
        background: 'rgba(255, 76, 76, 0.08)',
        borderRadius: '10px',
        padding: '14px',
        color: '#ffd6d6',
      }}
    >
      <div style={{ fontWeight: 700, marginBottom: '6px' }}>{title}</div>
      <div style={{ fontSize: '13px', color: '#ffb8b8' }}>{message || 'Please try again.'}</div>
      {typeof onRetry === 'function' && (
        <button
          onClick={onRetry}
          style={{
            marginTop: '10px',
            border: '1px solid rgba(255,255,255,0.25)',
            background: 'transparent',
            color: '#fff',
            borderRadius: '6px',
            padding: '6px 10px',
            cursor: 'pointer',
          }}
        >
          Retry
        </button>
      )}
    </div>
  );
}
