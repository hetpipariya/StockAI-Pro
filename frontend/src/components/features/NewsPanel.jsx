import React, { memo, useMemo } from 'react';

const MOCK_NEWS = [
  {
    title: 'TCS expected to show strong quarterly results',
    sentiment: 'positive',
  },
  {
    title: 'IT sector faces global slowdown concerns',
    sentiment: 'negative',
  },
  {
    title: 'Market remains sideways amid mixed signals',
    sentiment: 'neutral',
  },
];

const sentimentStyles = {
  positive: {
    text: '#4ade80',
    bg: 'rgba(34, 197, 94, 0.14)',
    border: 'rgba(34, 197, 94, 0.35)',
  },
  negative: {
    text: '#f87171',
    bg: 'rgba(239, 68, 68, 0.14)',
    border: 'rgba(239, 68, 68, 0.35)',
  },
  neutral: {
    text: '#cbd5e1',
    bg: 'rgba(148, 163, 184, 0.14)',
    border: 'rgba(148, 163, 184, 0.32)',
  },
};

const prettySentiment = (value) => String(value || '').charAt(0).toUpperCase() + String(value || '').slice(1).toLowerCase();

function NewsPanel({ symbol }) {
  const items = useMemo(() => {
    return MOCK_NEWS.map((news, idx) => ({
      id: `${symbol || 'market'}-${idx}`,
      ...news,
    }));
  }, [symbol]);

  return (
    <section style={{ marginBottom: '14px' }}>
      <div style={{
        fontSize: '11px',
        textTransform: 'uppercase',
        letterSpacing: '0.7px',
        color: 'var(--text-secondary)',
        marginBottom: '8px',
        fontFamily: 'var(--font-family-mono)',
      }}>
        Market News
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {items.map((item) => {
          const tone = sentimentStyles[item.sentiment] || sentimentStyles.neutral;
          return (
            <article
              key={item.id}
              className="news-item-card"
              style={{
                borderRadius: '10px',
                border: '1px solid var(--border-subtle, #1A2332)',
                background: 'rgba(5, 10, 14, 0.6)',
                padding: '10px 11px',
                transition: 'border-color 0.2s ease, transform 0.2s ease',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
                <p style={{ margin: 0, color: '#e2e8f0', fontSize: '12px', lineHeight: 1.42 }}>{item.title}</p>
                <span style={{
                  fontSize: '10px',
                  fontFamily: 'var(--font-family-mono)',
                  color: tone.text,
                  background: tone.bg,
                  border: `1px solid ${tone.border}`,
                  borderRadius: '999px',
                  padding: '4px 7px',
                  whiteSpace: 'nowrap',
                  textTransform: 'uppercase',
                  letterSpacing: '0.35px',
                }}>
                  {prettySentiment(item.sentiment)}
                </span>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

export default memo(NewsPanel);
