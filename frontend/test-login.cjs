const { chromium } = require('@playwright/test');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  
  console.log("Navigating to http://localhost:5173...");
  await page.goto('http://localhost:5173');
  
  console.log("Waiting for Person Number input...");
  const usernameInput = page.locator('input[placeholder*="Person Number"]');
  await usernameInput.waitFor({ state: 'visible', timeout: 5000 });
  await usernameInput.fill('7');
  
  console.log("Waiting for Password input...");
  const passwordInput = page.locator('input[type="password"]');
  await passwordInput.fill('testpass');
  
  console.log("Clicking Sign In...");
  await page.locator('button', { hasText: 'Sign In' }).click();
  
  console.log("Waiting for chat view...");
  try {
    // wait for the chat Composer to appear
    await page.locator('textarea').waitFor({ state: 'visible', timeout: 10000 });
    console.log("SUCCESS: Logged in and reached Chat View!");
  } catch (err) {
    console.error("FAILED: Did not reach Chat View in time.");
    
    // Check if there's an error message on the login screen
    const errorText = await page.locator('text=Sign-in failed').innerText().catch(() => null);
    if (errorText) {
      console.error("Login Error UI says: " + errorText);
    } else {
        const anyError = await page.evaluate(() => document.body.innerText);
        console.error("Body text: ", anyError);
    }
  }
  
  await browser.close();
})();
