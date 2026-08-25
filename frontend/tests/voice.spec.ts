import { test, expect } from '@playwright/test';

test.describe('Voice Input State Machine', () => {
  test.beforeEach(async ({ page }) => {
    // Pipe browser console logs to terminal
    page.on('console', msg => console.log(`BROWSER: ${msg.text()}`));

    // Disable assistant TTS to prevent it from auto-starting the mic and racing with our tests
    await page.addInitScript(() => window.localStorage.setItem('otl_voice_on', 'false'));

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
          workOrders: []
        })
      });
    });

    // Mock TTS endpoint to prevent proxy errors
    await page.route(/\/api\/tts/, async (route) => {
      await route.fulfill({ status: 200, body: 'mock-audio', contentType: 'audio/mpeg' });
    });

    // Mock the backend chat endpoint so we don't actually hit Gemini
    await page.route(/\/api\/chat/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'data: {"delta": "Hello from mock assistant"}\n\n'
      });
    });

    // Mock the SpeechRecognition API
    await page.addInitScript(() => {
      class MockSpeechRecognition {
        continuous = false;
        interimResults = false;
        lang = 'en-US';
        
        onstart: any = null;
        onresult: any = null;
        onerror: any = null;
        onend: any = null;
        onspeechstart: any = null;

        start() {
          // Expose the active instance to the global scope for the test to drive
          (window as any).mockMic = this;
          setTimeout(() => this.onstart && this.onstart(), 10);
        }

        stop() {
          setTimeout(() => {
            if (this.onend) this.onend();
          }, 10);
        }
        
        abort() {
          setTimeout(() => {
            if (this.onend) this.onend();
          }, 10);
        }

        simulateSpeech(text: string) {
          if (this.onspeechstart) this.onspeechstart();
          
          if (this.onresult) {
            this.onresult({
              resultIndex: 0,
              results: [
                Object.assign([ { transcript: text } ], { isFinal: false })
              ]
            });
          }
        }
        
        simulateFinalSpeech(text: string) {
          if (this.onspeechstart) this.onspeechstart();
          
          if (this.onresult) {
            this.onresult({
              resultIndex: 0,
              results: [
                Object.assign([ { transcript: text } ], { isFinal: true })
              ]
            });
          }
        }
      }

      (window as any).SpeechRecognition = MockSpeechRecognition;
      (window as any).webkitSpeechRecognition = MockSpeechRecognition;
    });
  });

  test('should not repopulate text box if Send is clicked during active dictation (Race Condition)', async ({ page }) => {
    await page.goto('/');

    // 1. Click the microphone button to start dictation
    const micBtn = page.getByRole('button', { name: /Speak/i });
    await expect(micBtn).toBeVisible();
    await micBtn.click();

    // Verify it turns to "Stop recording"
    await expect(page.getByRole('button', { name: /Stop recording/i })).toBeVisible();
    await expect(page.locator('textarea')).toHaveAttribute('placeholder', /Listening/i);

    // 2. Simulate the user speaking via our mock API
    await page.evaluate(() => {
      const mic = (window as any).mockMic;
      mic.simulateSpeech("I worked 4 hours on Alpha");
    });
    
    // Wait for the textarea to show the interim text
    const textarea = page.locator('textarea');
    await expect(textarea).toHaveValue('I worked 4 hours on Alpha');

    // 3. User manually clicks Send before the mic stops naturally
    const sendBtn = page.getByRole('button', { name: /Send/i });
    await sendBtn.click();

    // 4. Verify the text area is cleared immediately
    await expect(textarea).toHaveValue('');

    // 5. Explicitly wait for the mock mic's onend to fire (10ms delay in our mock abort)
    await page.waitForTimeout(50);

    // 6. Verify the text box REMAINS empty (the bug fix)
    await expect(textarea).toHaveValue('');

    // 6. Verify the text box REMAINS empty (the bug fix)
    await expect(textarea).toHaveValue('');
  });
  
  test('should auto-send transcribed text when manual mic button is toggled off', async ({ page }) => {
    await page.goto('/');

    // 1. Click the microphone button to start dictation
    const micBtn = page.getByRole('button', { name: /Speak/i });
    await expect(micBtn).toBeVisible();
    await micBtn.click();
    
    // Wait for the recording to actually start before accessing the mock mic
    await expect(page.getByRole('button', { name: /Stop recording/i })).toBeVisible();
    await expect(page.locator('textarea')).toHaveAttribute('placeholder', /Listening/i);
    
    // 2. Simulate the user speaking via our mock API
    await page.evaluate(() => {
      const mic = (window as any).mockMic;
      // We simulate final speech so that when it stops, finalText has the string
      mic.simulateFinalSpeech("I worked 2 hours on Beta");
    });
    
    const textarea = page.locator('textarea');
    await expect(textarea).toHaveValue('I worked 2 hours on Beta');

    // 3. User clicks the mic button again to STOP recording
    const stopMicBtn = page.getByRole('button', { name: /Stop recording/i });
    await stopMicBtn.click();
    
    // Wait for the mock mic to fire onend
    await page.waitForTimeout(50);

    // 4. Verify the text area is cleared automatically
    await expect(textarea).toHaveValue('');

    // 4. Verify the text area is cleared automatically
    await expect(textarea).toHaveValue('');
  });
});
