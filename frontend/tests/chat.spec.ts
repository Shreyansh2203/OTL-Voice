import { test, expect } from '@playwright/test';

test.describe('Chat View UI', () => {
  test.beforeEach(async ({ page }) => {
    // Mock authentication session
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

    // Mock the backend assignments endpoint to return fake project data
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

    // Mock TTS endpoint to prevent proxy errors
    await page.route(/\/api\/tts/, async (route) => {
      await route.fulfill({ status: 200, body: 'mock-audio', contentType: 'audio/mpeg' });
    });

    // Mock the chat streaming endpoint to return a simulated assistant response
    await page.route(/\/api\/chat/, async (route) => {
      console.log('INTERCEPTED CHAT:', route.request().url(), route.request().method());
      let isSubmission = false;
      try {
        const postData = route.request().postDataJSON();
        // Check if there are user messages that are NOT the kickoff message
        isSubmission = postData?.messages?.some(
          (m: any) => m.role === 'user' && m.content !== 'Please begin the session now.'
        );
      } catch (e) {
        // Ignore if no JSON body
      }

      const responseText = isSubmission 
        ? 'Timesheet submitted for 5 hours.' 
        : 'Hello, I am your assistant. You are assigned to Test Project Mock.';

      const sseContent = `data: {"delta": ${JSON.stringify(responseText)}}\n\n`;
      const sseDone = `data: {"done": true}\n\n`;
      
      try {
        await route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: sseContent + sseDone
        });
        console.log('FULFILLED CHAT ROUTE');
      } catch (e: any) {
        console.log('ERROR IN FULFILL:', e.message);
      }
    });
  });

  test('should display assistant greeting and project list', async ({ page }) => {
    await page.goto('/');

    // Verify Chat tab is active by checking the URL or the tab styling
    // Wait for the greeting message to appear
    const greeting = page.locator('.md', { hasText: "Test Project Mock" });
    await expect(greeting).toBeVisible({ timeout: 10000 });
  });

  test('should handle user chat input and show response', async ({ page }) => {
    await page.goto('/');
    
    // Type in the chat input box
    const input = page.locator('textarea');
    await input.waitFor({ state: 'visible' });
    await input.fill('I worked 5 hours on Mock Task 1 for Test Project Mock');
    await input.press('Enter');

    // Wait for the user's message to appear in the chat history
    const userMessage = page.locator('.bubble-row.user', { hasText: 'I worked 5 hours on Mock Task 1' });
    await expect(userMessage).toBeVisible();

    // Wait for the simulated assistant response to appear
    const assistantMessage = page.locator('.md', { hasText: 'Timesheet submitted for 5 hours.' });
    await expect(assistantMessage).toBeVisible();
  });

  test('should toggle voice button between on and off', async ({ page }) => {
    await page.goto('/');

    const voiceBtn = page.getByRole('button', { name: /Disable voice responses/i });
    await expect(voiceBtn).toBeVisible();
    await expect(voiceBtn).toHaveAttribute('aria-pressed', 'true');

    // Click to turn off voice
    await voiceBtn.click();
    const voiceOffBtn = page.getByRole('button', { name: /Enable voice responses/i });
    await expect(voiceOffBtn).toBeVisible();
    await expect(voiceOffBtn).toHaveAttribute('aria-pressed', 'false');

    // Click to turn voice back on
    await voiceOffBtn.click();
    await expect(page.getByRole('button', { name: /Disable voice responses/i })).toBeVisible();
  });
});
