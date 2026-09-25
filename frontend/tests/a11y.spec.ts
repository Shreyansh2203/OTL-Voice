import AxeBuilder from '@axe-core/playwright';
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
            'data: {"delta":"Welcome. What would you like to record?"}\n\n' +
            'data: {"done":true}\n\n',
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

test('chat view has no detectable accessibility violations', async ({
  page,
}) => {
  await page.goto('/');
  await expect(
    page.getByText('Welcome. What would you like to record?')
  ).toBeVisible();
  await page.waitForTimeout(500);

  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();

  expect(results.violations).toEqual([]);
});

test('mobile sidebar is hidden until explicitly opened and closable', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  const openNavigation = page.getByRole('button', { name: 'Open navigation' });
  const projects = page.getByRole('button', { name: 'Navigate to Projects' });

  await expect(openNavigation).toBeVisible();
  await expect(projects).toBeHidden();
  await openNavigation.click();
  await expect(projects).toBeVisible();
  await page
    .locator('#primary-navigation')
    .getByRole('button', { name: 'Close navigation' })
    .click();
  await expect(projects).toBeHidden();
});
