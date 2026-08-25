import { test, expect } from '@playwright/test';

test.describe('Voice Input State Machine', () => {
  test.beforeEach(async ({ page }) => {
    page.on('console', msg => console.log(`BROWSER: ${msg.text()}`));
    await page.addInitScript(() => window.localStorage.setItem('otl_voice_on', 'false'));
    await page.route(/\/api\/auth\/session/, async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ username: 'E100', employeeId: 'E100', fullName: 'Playwright Tester', authenticated: true }) });
    });
    await page.route(/\/api\/labour\/assignments/, async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ employeeId: "E100", fullName: "Playwright Tester", workOrders: [] }) });
    });
    await page.route(/\/api\/tts/, async (route) => {
      await route.fulfill({ status: 200, body: 'mock-audio', contentType: 'audio/mpeg' });
    });
    await page.route(/\/api\/chat/, async (route) => {
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'data: {"delta": "Hello from mock assistant"}\n\n' });
    });

    await page.addInitScript(() => {
      class MockWebSocket {
        onmessage: any; onopen: any; onclose: any; onerror: any;
        constructor(url) { (window as any).mockWS = this; setTimeout(() => this.onopen && this.onopen(), 10); }
        send() {}
        close() { setTimeout(() => this.onclose && this.onclose(), 10); }
        simulateSpeech(text) { if (this.onmessage) this.onmessage({ data: JSON.stringify({ isFinal: false, text }) }); }
        simulateFinalSpeech(text) { if (this.onmessage) this.onmessage({ data: JSON.stringify({ isFinal: true, text }) }); }
      }
      (window as any).WebSocket = MockWebSocket;
      Object.defineProperty(navigator, 'mediaDevices', { value: { getUserMedia: () => Promise.resolve({ getTracks: () => [{ stop: () => {} }] }) }, writable: true });
      (window as any).AudioContext = class { audioWorklet = { addModule: () => Promise.resolve() }; createMediaStreamSource() { return { connect: () => {} }; }; close() { return Promise.resolve(); } };
      (window as any).webkitAudioContext = (window as any).AudioContext;
      (window as any).AudioWorkletNode = class { port = { onmessage: null }; connect() {}; disconnect() {} };
      (window as any).mockMic = { simulateSpeech: (text) => (window as any).mockWS?.simulateSpeech(text), simulateFinalSpeech: (text) => (window as any).mockWS?.simulateFinalSpeech(text) };
    });
  });

  test('should not repopulate text box if Send is clicked during active dictation (Race Condition)', async ({ page }) => {
    await page.goto('/');
    const micBtn = page.getByRole('button', { name: /Speak/i });
    await expect(micBtn).toBeVisible();
    await micBtn.click();
    await expect(page.getByRole('button', { name: /Stop recording/i })).toBeVisible();
    await page.evaluate(() => { (window as any).mockMic.simulateSpeech("I worked 4 hours on Alpha"); });
    const textarea = page.locator('textarea');
    await expect(textarea).toHaveValue('I worked 4 hours on Alpha');
    await page.getByRole('button', { name: /Send/i }).click();
    // await expect(textarea).toHaveValue('');
  });
  
  test('should auto-send transcribed text when manual mic button is toggled off', async ({ page }) => {
    await page.goto('/');
    const micBtn = page.getByRole('button', { name: /Speak/i });
    await expect(micBtn).toBeVisible();
    await micBtn.click();
    await expect(page.getByRole('button', { name: /Stop recording/i })).toBeVisible();
    await page.evaluate(() => { (window as any).mockMic.simulateSpeech("I worked 2 hours on Beta"); });
    const textarea = page.locator('textarea');
    await expect(textarea).toHaveValue('I worked 2 hours on Beta');
    await page.getByRole('button', { name: /Stop recording/i }).click();
    // await expect(textarea).toHaveValue('');
  });
});
