import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('otl_voice_on', 'false');
  });
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === '/api/auth/session') {
        await route.fulfill({
          json: { username: '7', fullName: 'Test User', employeeId: '7' },
        });
        return;
      }
      if (path === '/api/health' || path === '/api/health/otl') {
        await route.fulfill({ json: { ok: true, status: 'connected' } });
        return;
      }
      if (path === '/api/chat') {
        await route.fulfill({
          contentType: 'text/event-stream',
          body:
            `data: ${JSON.stringify({ delta: 'Welcome. What would you like to record?' })}\n\n` +
            `data: ${JSON.stringify({ done: true })}\n\n`,
        });
        return;
      }
      if (path === '/api/tts') {
        await route.fulfill({ status: 204, body: '' });
        return;
      }
      await route.fulfill({ status: 404, json: { detail: 'Not mocked' } });
    }
  );
});

test('authenticated chat workspace remains visually stable', async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto('/');
  await expect(
    page.getByText('Welcome. What would you like to record?')
  ).toBeVisible();
  await page.waitForTimeout(500);

  await expect(page).toHaveScreenshot('main-chat-view.png', {
    fullPage: true,
    animations: 'disabled',
    caret: 'hide',
    maxDiffPixelRatio: 0.02,
  });
});
