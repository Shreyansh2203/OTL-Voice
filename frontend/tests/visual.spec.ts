import { test, expect } from '@playwright/test';

test.describe('Visual Regression Tests', () => {
  test.beforeEach(async ({ page }) => {
    await page.route(/\/api\/auth\/session/, async (route) => {
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

    await page.route(/\/api\/labour\/assignments/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          employeeId: "E100",
          fullName: "Playwright Tester",
          workOrders: [
            {
              workOrder: "WO-1234",
              projects: [
                {
                  projectId: "proj-1",
                  projectNo: "1234",
                  projectName: "Test Project Mock",
                  tasks: [
                    { taskId: "task-1", taskNo: "T1", taskName: "Mock Task 1" }
                  ]
                }
              ]
            }
          ]
        })
      });
    });

    await page.route(/\/api\/tts/, async (route) => {
      await route.fulfill({ status: 200, body: 'mock-audio', contentType: 'audio/mpeg' });
    });

    await page.route(/\/api\/chat/, async (route) => {
      const responseText = 'Hello, I am your assistant. You are assigned to Test Project Mock.';
      const sseContent = `data: {"delta": ${JSON.stringify(responseText)}}\n\n`;
      const sseDone = `data: {"done": true}\n\n`;
      
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: sseContent + sseDone
      });
    });
  });

  test('Main Chat View should match screenshot', async ({ page }) => {
    await page.goto('/');
    const greeting = page.locator('.md', { hasText: "Test Project Mock" });
    await expect(greeting).toBeVisible({ timeout: 10000 });
    await expect(page).toHaveScreenshot('main-chat-view.png', {
      maxDiffPixelRatio: 0.05
    });
  });
});
