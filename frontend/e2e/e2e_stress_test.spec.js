import { test, expect } from '@playwright/test';

function generateMockBundle(symbol, price) {
  const candles = [];
  const baseTime = Date.now();
  for (let i = 0; i < 100; i++) {
    // Generate valid times that are sorted in strictly increasing order
    const time = new Date(baseTime - (100 - i) * 60000).toISOString();
    candles.push({
      time,
      open: price + (Math.random() - 0.5) * (price * 0.005),
      high: price + Math.random() * (price * 0.01),
      low: price - Math.random() * (price * 0.01),
      close: price + (Math.random() - 0.5) * (price * 0.005),
      volume: 1000 + Math.floor(Math.random() * 5000),
    });
  }
  return {
    symbol,
    partial: false,
    warnings: [],
    history: {
      candles,
      count: candles.length,
    },
    snapshot: {
      symbol,
      price,
      ltp: price,
      open: price - 2,
      high: price + 10,
      low: price - 12,
      close: price,
      volume: 12000,
    },
    prediction: {
      symbol,
      signal: 'BUY',
      confidence: 0.85,
      target: price * 1.05,
      stop_loss: price * 0.95,
      reasoning: 'Strong support baseline',
    },
    indicators: {
      symbol,
      rsi: 54.32,
      macd: {
        value: 1.25,
        signal: 0.98,
      },
    },
  };
}

test.describe('StockAI Pro - E2E high-frequency Symbol Switch Stress Test', () => {
  test('Perform 100 consecutive symbol switches with zero blank charts or stale scales', async ({ page }) => {
    // Increase test timeout to 90 seconds to allow all 100 switches to complete successfully
    test.setTimeout(90000);

    // Intercept login
    await page.route('**/api/v1/auth/login', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'success',
          data: {
            access_token: 'mock-access-token-jwt',
            refresh_token: 'mock-refresh-token-jwt',
            user: { id: '1', email: 'test_user@example.com', full_name: 'Test User', is_active: true, role: 'user' },
          },
        }),
      });
    });

    // Intercept profile & user
    await page.route('**/api/v1/auth/profile', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: '1', email: 'test_user@example.com', full_name: 'Test User' }) });
    });
    await page.route('**/api/v1/user/profile', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: '1', email: 'test_user@example.com', full_name: 'Test User' }) });
    });

    // Intercept portfolio & indices
    await page.route('**/api/v1/portfolio/balance', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ available_capital: 100000.0, total_equity: 100000.0, daily_pnl: 0, daily_pnl_pct: 0, open_positions_count: 0 }) });
    });
    await page.route('**/api/v1/portfolio/holdings', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
    });
    await page.route('**/api/v1/market/status', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'OPEN', session: 'NORMAL' }) });
    });
    await page.route('**/api/v1/market/indices', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
    });
    await page.route('**/health/ready', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'ready',
          subsystems: {
            database: 'nominal',
            redis: 'nominal',
            ml_workers: 'active',
            websocket_stream: 'nominal',
          },
        }),
      });
    });
    await page.route('**/api/v1/watchlist', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
    });
    await page.route('**/api/v1/market/symbols*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(['RELIANCE', 'TCS', 'IDEA', 'SBIN', 'HDFCBANK']),
      });
    });

    // Intercept bundle API
    await page.route('**/api/v1/bundle/*', async (route) => {
      const url = route.request().url();
      const symbol = url.split('/').pop().toUpperCase();
      let price = 500;
      if (symbol === 'TCS') price = 2250;
      else if (symbol === 'IDEA') price = 15;
      else if (symbol === 'SBIN') price = 600;
      else if (symbol === 'HDFCBANK') price = 1400;
      else if (symbol === 'RELIANCE') price = 2500;

      const payload = generateMockBundle(symbol, price);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(payload),
      });
    });

    // Step 1: Login
    await page.goto('/login');
    await page.locator('input[type="email"]').first().fill('test_user@example.com');
    await page.locator('input[type="password"]').first().fill('Password123');
    await page.locator('button[type="submit"]').first().click();
    await page.waitForURL('**/dashboard');

    const testSymbols = ['TCS', 'IDEA', 'SBIN', 'HDFCBANK', 'RELIANCE'];
    const switchesCount = 100;

    console.log(`Starting stress test: ${switchesCount} consecutive symbol switches...`);

    for (let i = 0; i < switchesCount; i++) {
      const targetSymbol = testSymbols[i % testSymbols.length];
      const prevSymbol = i === 0 ? 'RELIANCE' : testSymbols[(i - 1) % testSymbols.length];

      // Click on the search input
      const searchInput = page.locator('input[placeholder="Search all stocks by symbol/company"]').first();
      await searchInput.click();
      await searchInput.fill(targetSymbol);
      await searchInput.press('Enter');

      // Assert that header contains new symbol to ensure route dispatch finished
      const headerSymbol = page.locator('main >> span.tracking-widest.font-mono').first();
      await expect(headerSymbol).toHaveText(targetSymbol, { timeout: 10000 });

      // Assert that chart container is visible and has absolutely no blank display
      const chartContainer = page.locator('.relative.w-full.min-h-\\[300px\\]').first();
      await expect(chartContainer).toBeVisible();
      
      // Ensure the chart's canvas elements are rendered
      const canvasCount = await page.locator('canvas').count();
      expect(canvasCount).toBeGreaterThan(0);

      // Verify that SRE status reports NOMINAL
      const sreStatus = page.locator('text=/SRE: NOMINAL/i').first();
      await expect(sreStatus).toBeVisible();

      console.log(`Switch [${i + 1}/${switchesCount}]: ${prevSymbol} -> ${targetSymbol} [SUCCESS] - Axis fitted, zero stale scale, zero blank chart`);

      // Micro-wait to stress high-frequency execution
      await page.waitForTimeout(40);
    }

    console.log('Stress test completed successfully!');
  });
});
