import { chromium } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';

const EMAIL = 'hetpipariya81@gmail.com';
const PASSWORD = 'PHet07310';
const BASE_URL = 'http://localhost:5173';
const STOCKS_TO_TEST = ['RELIANCE', 'SBIN', 'TCS', 'INFY'];
const TIMEFRAMES = ['1m', '5m', '15m', '1h', '1d'];

// Save screenshots directly to the conversation's brain/artifacts folder
const SCREENSHOT_DIR = 'C:\\Users\\PIPARIYA\\.gemini\\antigravity\\brain\\c12b423f-6d6a-42b7-bd61-264ac4e6d4f6';

async function runTest() {
  console.log('🚀 Starting headed StockAI Pro live dashboard test...');
  console.log(`🔑 Credentials: ${EMAIL}`);
  console.log(`📈 Stocks to test: ${STOCKS_TO_TEST.join(', ')}`);
  console.log(`⏱️ Timeframes to test: ${TIMEFRAMES.join(', ')}`);

  // Ensure screenshot directory exists
  if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  }

  // Launch headed browser so the user can watch the automation
  const browser = await chromium.launch({
    headless: false,
    slowMo: 800, // Slow down operations so they are easy to watch
    args: ['--start-maximized']
  });

  const context = await browser.newContext({
    viewport: null // Uses natural screen size or maximized size
  });

  const page = await context.newPage();

  try {
    // 1. Visit Login Page
    console.log(`\nStep 1: Navigating to ${BASE_URL}/login...`);
    await page.goto(`${BASE_URL}/login`);
    await page.waitForLoadState('networkidle');

    // 2. Perform Login Flow
    console.log('Step 2: Performing login...');
    const emailInput = page.locator('input[type="email"]').first();
    await emailInput.fill(EMAIL);
    
    const passwordInput = page.locator('input[type="password"]').first();
    await passwordInput.fill(PASSWORD);

    const submitButton = page.locator('button[type="submit"]').first();
    await submitButton.click();

    // 3. Wait for Dashboard to Load
    console.log('Step 3: Waiting for dashboard redirection...');
    await page.waitForURL('**/dashboard', { timeout: 15000 });
    console.log('✅ Login successful! Reached /dashboard');

    // Wait a bit for the initial dashboard render
    await page.waitForTimeout(3000);

    // 4. Test each stock and timeframe
    for (const symbol of STOCKS_TO_TEST) {
      console.log(`\n🔍 Testing Symbol: ${symbol}`);

      // Search for the symbol using the search bar
      const searchInput = page.locator('input[placeholder="Search all stocks by symbol/company"]').first();
      await searchInput.click();
      await page.waitForTimeout(500);
      
      // Clear input by selecting all and typing/deleting, or using selectText
      await searchInput.focus();
      await page.keyboard.press('Control+A');
      await page.keyboard.press('Backspace');
      await searchInput.fill(symbol);
      await page.waitForTimeout(1000);
      
      console.log(`⌨️ Typed '${symbol}', submitting search...`);
      await searchInput.press('Enter');

      // Assert that header contains the new symbol to verify load dispatch
      const headerSymbol = page.locator('main >> span.tracking-widest.font-mono').first();
      try {
        await page.waitForFunction(
          (sym) => {
            const el = document.querySelector('main span.tracking-widest.font-mono');
            return el && el.textContent.trim().toUpperCase() === sym;
          },
          symbol,
          { timeout: 10000 }
        );
        console.log(`✅ Symbol header updated to ${symbol}`);
      } catch (err) {
        console.warn(`⚠️ Warning: Header did not update to ${symbol} within 10s:`, err.message);
      }

      // Wait a moment for initial chart load for this symbol
      await page.waitForTimeout(2000);

      // Now test each timeframe
      for (const tf of TIMEFRAMES) {
        const tfLabel = tf.toUpperCase();
        console.log(`⏱️ Selecting Timeframe: ${tfLabel}`);

        // Find the timeframe button
        const tfButton = page.locator('button').filter({ hasText: new RegExp(`^${tfLabel}$`) }).first();
        if (await tfButton.count() > 0) {
          await tfButton.click();
          console.log(`👉 Clicked timeframe button: ${tfLabel}`);
        } else {
          console.warn(`⚠️ Could not find timeframe button: ${tfLabel}`);
          continue;
        }

        // Wait a few seconds for the chart data to be fetched and rendered
        await page.waitForTimeout(4000);

        // Take a screenshot of the dashboard
        const screenshotPath = path.join(SCREENSHOT_DIR, `screenshot_${symbol}_${tf}.png`);
        await page.screenshot({ path: screenshotPath });
        console.log(`📸 Screenshot saved: ${screenshotPath}`);
      }
    }

    console.log('\n🌟 All tests completed successfully!');
    console.log('Waiting 5 seconds before closing the browser...');
    await page.waitForTimeout(5000);

  } catch (error) {
    console.error('❌ Error during testing:', error);
    // Take an error screenshot if something failed
    try {
      const errScreenshotPath = path.join(SCREENSHOT_DIR, 'error_screenshot.png');
      await page.screenshot({ path: errScreenshotPath });
      console.log(`📸 Error screenshot saved: ${errScreenshotPath}`);
    } catch (e) {
      console.error('Failed to capture error screenshot:', e);
    }
  } finally {
    await browser.close();
    console.log('👋 Browser session closed.');
  }
}

runTest();
