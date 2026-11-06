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
          json: {
            username: '7',
            employeeId: '7',
            fullName: 'Playwright Tester',
          },
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
          body: 'data: {"done":true}\n\n',
        });
        return;
      }
      if (path === '/api/otl/timecards') {
        await route.fulfill({
          json: {
            items: [
              {
                timeRecordEventRequestId: '1001',
                timeRecordEvent: [
                  {
                    startTime: '2025-01-14T09:00:00.000Z',
                    stopTime: '2025-01-14T17:00:00.000Z',
                    measure: 8,
                    eventStatus: 'SUBMITTED',
                    timeRecordEventAttribute: [
                      {
                        attributeName: 'Comment',
                        attributeValue:
                          'Project: Mock Architecture | Task: Design',
                      },
                    ],
                  },
                ],
              },
              {
                timeRecordEventRequestId: '1002',
                timeRecordEvent: [
                  {
                    startTime: '2025-01-15T10:00:00.000Z',
                    stopTime: '2025-01-15T15:00:00.000Z',
                    measure: 5,
                    eventStatus: 'APPROVED',
                    timeRecordEventAttribute: [
                      {
                        attributeName: 'Comment',
                        attributeValue: 'Project: Mock Implementation',
                      },
                    ],
                  },
                ],
              },
            ],
          },
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

test('renders submitted and approved history with parsed details', async ({
  page,
}) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Navigate to History' }).click();

  await expect(page.getByText('Mock Architecture')).toBeVisible();
  await expect(page.getByText('8', { exact: true })).toBeVisible();
  await expect(page.getByText(/SUBMITTED/i).first()).toBeVisible();
  await expect(page.getByText('Mock Implementation')).toBeVisible();
  await expect(page.getByText('5', { exact: true })).toBeVisible();
  await expect(page.getByText(/APPROVED/i).first()).toBeVisible();
});
