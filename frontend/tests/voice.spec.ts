import { test, expect } from '@playwright/test';

test.describe('Voice Input State Machine', () => {
  test.beforeEach(async ({ page }) => {
    page.on('console', (msg) => console.log(`BROWSER: ${msg.text()}`));
    await page.addInitScript(() => window.localStorage.setItem('otl_voice_on', 'false'));
    await page.route(/\/api\/auth\/session/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          username: 'E100',
          employeeId: 'E100',
          fullName: 'Playwright Tester',
          authenticated: true,
        }),
      });
    });
    await page.route(/\/api\/labour\/assignments/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ employeeId: 'E100', fullName: 'Playwright Tester', workOrders: [] }),
      });
    });
    await page.route(/\/api\/tts/, async (route) => {
      await route.fulfill({ status: 200, body: 'mock-audio', contentType: 'audio/mpeg' });
    });
    await page.route(/\/api\/chat/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'data: {"delta": "Hello from mock assistant"}\n\n',
      });
    });

    await page.addInitScript(() => {
      class MockSpeechRecognition {
        continuous = true;
        interimResults = true;
        lang = 'en-US';
        maxAlternatives = 1;
        onresult: any = null;
        onerror: any = null;
        onend: any = null;
        onspeechstart: any = null;
        onaudiostart: any = null;

        constructor() {
          (window as any).mockRecognition = this;
        }

        start() {
          if (this.onspeechstart) this.onspeechstart();
        }

        stop() {
          if (this.onend) this.onend();
        }

        abort() {
          if (this.onend) this.onend();
        }

        simulateSpeech(text: string) {
          if (this.onresult) {
            this.onresult({
              resultIndex: 0,
              results: [
                {
                  0: { transcript: text },
                  isFinal: false,
                  length: 1,
                },
              ],
            });
          }
        }

        simulateFinalSpeech(text: string) {
          if (this.onresult) {
            this.onresult({
              resultIndex: 0,
              results: [
                {
                  0: { transcript: text },
                  isFinal: true,
                  length: 1,
                },
              ],
            });
          }
        }
      }

      (window as any).SpeechRecognition = MockSpeechRecognition;
      (window as any).webkitSpeechRecognition = MockSpeechRecognition;
      (window as any).mockMic = {
        simulateSpeech: (text: string) => (window as any).mockRecognition?.simulateSpeech(text),
        simulateFinalSpeech: (text: string) => (window as any).mockRecognition?.simulateFinalSpeech(text),
      };
    });
  });

  test('should not repopulate text box if Send is clicked during active dictation (Race Condition)', async ({ page }) => {
    await page.goto('/');
    const micBtn = page.getByRole('button', { name: /Speak/i });
    await expect(micBtn).toBeVisible();
    await micBtn.click();
    await expect(page.getByRole('button', { name: /Stop recording/i })).toBeVisible();
    await page.evaluate(() => {
      (window as any).mockMic.simulateSpeech('I worked 4 hours on Alpha');
    });
    const textarea = page.locator('textarea');
    await expect(textarea).toHaveValue('I worked 4 hours on Alpha');
    await page.getByRole('button', { name: /Send/i }).click();
  });

  test('should auto-send transcribed text when manual mic button is toggled off', async ({ page }) => {
    await page.goto('/');
    const micBtn = page.getByRole('button', { name: /Speak/i });
    await expect(micBtn).toBeVisible();
    await micBtn.click();
    await expect(page.getByRole('button', { name: /Stop recording/i })).toBeVisible();
    await page.evaluate(() => {
      (window as any).mockMic.simulateSpeech('I worked 2 hours on Beta');
    });
    const textarea = page.locator('textarea');
    await expect(textarea).toHaveValue('I worked 2 hours on Beta');
    await page.getByRole('button', { name: /Stop recording/i }).click();
  });
});
