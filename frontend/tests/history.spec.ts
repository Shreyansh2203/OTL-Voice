import { test, expect } from '@playwright/test';

test.describe('Timecard History UI', () => {
  test.beforeEach(async ({ page }) => {
    // Mock authentication session
    await page.route('**/api/auth/session', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          username: 'E100', employeeId: 'E100',
          fullName: 'Playwright Tester',
          authenticated: true
        })
      });
    });

    // Mock the backend timecards endpoint to return fake history data
    await page.route('**/api/otl/timecards*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            {
              timeRecordEventRequestId: "1001",
              timeRecordEvent: [
                {
                  startTime: "2025-01-14T09:00:00.000Z",
                  stopTime: "2025-01-14T17:00:00.000Z",
                  measure: 8,
                  eventStatus: "SUBMITTED",
                  timeRecordEventAttribute: [
                    { attributeName: "Comment", attributeValue: "Project: Mock Architecture | Task: Design" }
                  ]
                }
              ]
            },
            {
              timeRecordEventRequestId: "1002",
              timeRecordEvent: [
                {
                  startTime: "2025-01-15T10:00:00.000Z",
                  stopTime: "2025-01-15T15:00:00.000Z",
                  measure: 5,
                  eventStatus: "APPROVED",
                  timeRecordEventAttribute: [
                    { attributeName: "Comment", attributeValue: "Project: Mock Implementation" }
                  ]
                }
              ]
            }
          ]
        })
      });
    });
  });

  test('should display historical timecards correctly', async ({ page }) => {
    // Stub the chat & TTS endpoints so the initial kickoff resolves quickly
    await page.route('**/api/chat', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'data: {"done":true}\n\n',
      });
    });
    await page.route('**/api/tts', async (route) => {
      await route.fulfill({ status: 204, body: '' });
    });

    await page.goto('/');

    // Wait for the initial chat stream to settle before interacting with tabs
    await page.waitForLoadState('networkidle');

    // Navigate to History tab — use force click to handle transient detach
    const historyTab = page.locator('button', { hasText: 'History' });
    await historyTab.waitFor({ state: 'visible' });
    await historyTab.click();

    // Verify that the table rows are rendered
    await expect(page.getByText('Mock Architecture')).toBeVisible();
    await expect(page.getByText('8', { exact: true })).toBeVisible();
    await expect(page.getByText('SUBMITTED', { exact: false }).first()).toBeVisible();

    await expect(page.getByText('Mock Implementation')).toBeVisible();
    await expect(page.getByText('5', { exact: true })).toBeVisible();
    await expect(page.getByText('APPROVED', { exact: false }).first()).toBeVisible();
  });
});
