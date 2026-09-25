import { expect, test } from '@playwright/test';

test.skip(
  ({ browserName }) => browserName !== 'chromium',
  'Microphone gesture automation is Chromium-specific.'
);

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('otl_voice_on', 'true');
    (
      window as Window & { __OTL_E2E_BROWSER_SPEECH__?: boolean }
    ).__OTL_E2E_BROWSER_SPEECH__ = true;
    class MockSpeechRecognition {
      continuous = false;
      interimResults = false;
      lang = 'en-US';
      maxAlternatives = 1;
      closed = false;
      onspeechstart: (() => void) | null = null;
      onresult:
        | ((event: {
            results: Array<
              Array<{ transcript: string; confidence: number }> & {
                isFinal: boolean;
              }
            >;
          }) => void)
        | null = null;
      onerror: ((event: { error: string }) => void) | null = null;
      onend: (() => void) | null = null;
      start() {
        this.onspeechstart?.();
        const result = [
          { transcript: '4 hours on Alpha', confidence: 0.95 },
        ] as Array<{ transcript: string; confidence: number }> & {
          isFinal: boolean;
        };
        result.isFinal = true;
        this.onresult?.({ results: [result] });
      }
      stop() {
        this.closed = true;
        this.onend?.();
      }
      abort() {
        this.closed = true;
      }
    }
    Object.defineProperty(window, 'SpeechRecognition', {
      configurable: true,
      value: MockSpeechRecognition,
    });
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
        let hasCapturedTime = false;
        try {
          const payload = route.request().postDataJSON() as {
            messages?: Array<{ content?: string }>;
          };
          hasCapturedTime = (payload.messages?.length ?? 0) > 1;
        } catch {
          hasCapturedTime = false;
        }
        await route.fulfill({
          contentType: 'text/event-stream',
          body: `data: ${JSON.stringify({
            delta: hasCapturedTime ? 'I captured 4 hours on Alpha.' : '',
          })}\n\ndata: {"done":true}\n\n`,
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

test('microphone input is opt-in and final speech becomes a user message', async ({
  page,
}) => {
  await page.goto('/');
  const input = page.getByRole('textbox', { name: /message/i });
  const micButton = page.getByRole('button', { name: 'Speak' });
  await expect(input).toBeEnabled();
  await expect(micButton).toBeVisible();

  await micButton.click();

  await expect(page.getByText('4 hours on Alpha')).toBeVisible();
  await expect(page.getByText('I captured 4 hours on Alpha.')).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Stop recording' })
  ).toBeVisible();
  await expect(input).toBeEnabled();
});

test('turning voice off releases the active microphone session', async ({
  page,
}) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Speak' }).click();
  await expect(
    page.getByRole('button', { name: 'Stop recording' })
  ).toBeVisible();

  await page.getByRole('button', { name: 'Disable voice responses' }).click();

  await expect(page.getByRole('button', { name: 'Speak' })).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Stop recording' })
  ).toHaveCount(0);
});
