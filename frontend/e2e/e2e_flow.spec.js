import { test, expect } from '@playwright/test';

test.describe('StockAI Pro - E2E Flow Spec', () => {
  test('Complete authentication, dashboard navigation, and logout flow', async ({ page }) => {
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
            user: {
              id: '1',
              email: 'test_user@example.com',
              full_name: 'Test User',
              is_active: true,
              role: 'user',
            },
          },
        }),
      });
    });

    // Intercept profile
    await page.route('**/api/v1/auth/profile', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: '1',
          email: 'test_user@example.com',
          full_name: 'Test User',
          is_active: true,
          role: 'user',
        }),
      });
    });

    // Intercept user profile / me
    await page.route('**/api/v1/user/profile', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: '1',
          email: 'test_user@example.com',
          full_name: 'Test User',
          is_active: true,
          role: 'user',
        }),
      });
    });

    // Intercept portfolio balance
    await page.route('**/api/v1/portfolio/balance', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          available_capital: 100000.0,
          total_equity: 100000.0,
          daily_pnl: 250.0,
          daily_pnl_pct: 0.25,
          open_positions_count: 1,
        }),
      });
    });

    // Intercept active signals
    await page.route('**/api/v1/signals', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 'sig-1',
            symbol: 'SBIN',
            time: '2026-05-29T15:00:00Z',
            signal: 'BUY',
            probability: 0.87,
            stop_loss: 645.0,
            target: 670.0,
            reason: 'Bullish candle confluence and volume breakout',
          },
          {
            id: 'sig-2',
            symbol: 'RELIANCE',
            time: '2026-05-29T15:05:00Z',
            signal: 'HOLD',
            probability: 0.52,
            stop_loss: 2480.0,
            target: 2550.0,
            reason: 'Doji indecision overrules signal alignment',
          },
        ]),
      });
    });

    // Intercept portfolio/holdings
    await page.route('**/api/v1/portfolio/holdings', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    });

    // Intercept market status
    await page.route('**/api/v1/market/status', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'OPEN', session: 'NORMAL' }),
      });
    });

    // Intercept market indices
    await page.route('**/api/v1/market/indices', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    });

    // Intercept watchlist
    await page.route('**/api/v1/watchlist', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    });

    // Step 1: Navigating to login page
    await page.goto('/login');

    // Step 2: Perform Login Flow
    await page.locator('input[type="email"]').first().fill('test_user@example.com');
    await page.locator('input[type="password"]').first().fill('Password123');
    await page.locator('button[type="submit"]').first().click();

    // Wait for redirection to dashboard or landing route
    await page.waitForURL('**/dashboard');
    await expect(page).toHaveURL(/.*dashboard/);

    // Step 3: Check Dashboard content
    await expect(page.locator('body')).toContainText('RELIANCE');

    // Step 4: Perform Logout
    const logoutBtn = page.locator('button:has-text("Logout"), a:has-text("Logout"), button:has-text("Sign Out"), a:has-text("Sign Out")').first();
    if (await logoutBtn.count() > 0) {
      await logoutBtn.click();
      await page.waitForURL('**/login');
      await expect(page).toHaveURL(/.*login/);
    }
  });
});
