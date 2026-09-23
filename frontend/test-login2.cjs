const { chromium } = require('@playwright/test');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  
  page.on('response', async (res) => {
    if (res.url().includes('/api/auth/login')) {
       console.log("Login API Response:", await res.text());
    }
  });

  await page.goto('http://localhost:5177');
  await page.locator('input[placeholder*="Person Number"]').fill('7');
  await page.locator('input[type="password"]').fill('testpass');
  await page.locator('button', { hasText: 'Sign In' }).click();
  
  await page.waitForTimeout(3000);
  
  const anyError = await page.evaluate(() => document.body.innerText);
  console.log("Body text: ", anyError);
  
  await browser.close();
})();
