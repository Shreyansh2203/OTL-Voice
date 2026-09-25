import { expect, test, type Page, type Route } from '@playwright/test';

const identity = {
  username: '7',
  fullName: 'Test User',
  employeeId: '7',
};

const reviewEntry = {
  employeeNumber: '7',
  employeeName: 'Test User',
  projectId: 'PRJ-1',
  projectNo: 'PA-1',
  projectName: 'Operations',
  workOrder: 'WO-9',
  taskId: 'TASK-1',
  taskDetails: 'Reviewed weekly payroll entries',
  hours: 2.5,
  date: '2026-09-25',
  startTime: '09:00',
  stopTime: '11:30',
  payrollTimeType: 'Regular',
  expenditureType: 'Regular Time',
  currencyCode: 'USD',
};

const isApiPath = (url: URL) => url.pathname.startsWith('/api/');

async function installMocks(
  page: Page,
  assistantDelta = '',
  assistantDelayMs = 0
) {
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  await page.addInitScript(() => {
    localStorage.setItem('otl_voice_on', 'false');
  });
  await page.route(isApiPath, async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/auth/session') {
      await route.fulfill({ json: identity });
      return;
    }
    if (path === '/api/health' || path === '/api/health/otl') {
      await route.fulfill({ json: { ok: true, status: 'connected' } });
      return;
    }
    if (path === '/api/chat') {
      let isKickoff = false;
      try {
        const payload = route.request().postDataJSON() as {
          messages?: Array<{ content?: string }>;
        };
        isKickoff =
          payload.messages?.length === 1 &&
          payload.messages[0]?.content === 'Please begin the session now.';
      } catch {
        isKickoff = false;
      }
      const delta = isKickoff ? '' : assistantDelta;
      if (assistantDelayMs && delta) {
        await new Promise((resolve) => setTimeout(resolve, assistantDelayMs));
      }
      const body =
        `data: ${JSON.stringify({ delta })}\n\n` +
        `data: ${JSON.stringify({ done: true })}\n\n`;
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body,
      });
      return;
    }
    if (path === '/api/tts') {
      await route.fulfill({
        status: 200,
        contentType: 'audio/mpeg',
        body: Buffer.from([0, 0, 0, 0]),
      });
      return;
    }
    await route.fulfill({ status: 404, json: { detail: 'Not mocked' } });
  });
}
test.beforeEach(async ({ page }) => {
  await installMocks(page);
});

test.afterEach(async ({ page }) => {
  await page.evaluate(() => {
    localStorage.clear();
  });
});

async function readyComposer(page: Page) {
  const input = page.getByRole('textbox', { name: /message/i });
  await expect(input).toBeEnabled({ timeout: 15_000 });
  return input;
}

test('lands in the authenticated voice workspace', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Assistant' })).toBeVisible();
  await expect(page.getByText('Oracle Fusion Connected')).toBeVisible();
  await expect(
    page.getByText(/Nothing is sent to OTL until you approve/i)
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: /New conversation/i })
  ).toBeVisible();
  await expect(page.getByRole('button', { name: /Sign out/i })).toBeVisible();
});

test('accepts chat input and shows the loading then response states', async ({
  page,
}) => {
  await installMocks(page, 'Thanks, I captured that.', 800);
  await page.goto('/');
  const input = await readyComposer(page);
  await input.fill('Capture my time');
  await page.getByRole('button', { name: /send/i }).click();

  await expect(page.getByText('Capture my time')).toBeVisible();
  await expect(input).toBeDisabled();
  await expect(page.getByText('Thanks, I captured that.')).toBeVisible();
  await expect(input).toBeEnabled();
  await expect(page.getByRole('button', { name: /send/i })).toBeDisabled();
});

test('renders all review fields for a valid assistant payload', async ({
  page,
}) => {
  const payload = `Review this before approval.\n\`\`\`json\n${JSON.stringify({
    entries: [reviewEntry],
  })}\n\`\`\``;
  await installMocks(page, payload);
  await page.goto('/');
  const input = await readyComposer(page);
  await input.fill('Record my time');
  await page.getByRole('button', { name: /send/i }).click();

  await expect(page.getByText('Review Timesheet')).toBeVisible();
  await expect(page.getByText('Awaiting Approval')).toBeVisible();
  await expect(page.getByLabel('Project number')).toHaveValue('PA-1');
  await expect(page.getByLabel('Work order')).toHaveValue('WO-9');
  await expect(page.getByLabel('Task details')).toHaveValue(
    'Reviewed weekly payroll entries'
  );
  await expect(page.getByRole('spinbutton', { name: 'Hours' })).toHaveValue(
    '2.5'
  );
  await expect(page.getByLabel('Date')).toHaveValue('2026-09-25');
  await expect(page.getByLabel('Stop time (optional)')).toHaveValue('11:30');
  await expect(page.getByLabel('Payroll time type')).toHaveValue('Regular');
  await expect(page.getByLabel('Expenditure type')).toHaveValue('Regular Time');
  await expect(page.getByLabel('Currency code')).toHaveValue('USD');
  await expect(page.getByText('{"entries"')).toHaveCount(0);
});

test('opens a complete manual fallback for malformed JSON', async ({
  page,
}) => {
  await installMocks(
    page,
    'I could not finalize this.\n```json\n{"entries":[\n```'
  );
  await page.goto('/');
  const input = await readyComposer(page);
  await input.fill('Capture malformed time');
  await page.getByRole('button', { name: /send/i }).click();

  await expect(
    page.getByText(/did not return a valid timesheet payload/i)
  ).toBeVisible();
  await expect(
    page.getByRole('heading', { name: 'Manual Timesheet Review' })
  ).toBeVisible();
  await expect(page.getByLabel('Employee number')).toHaveValue('7');
  await expect(page.getByLabel('Employee name')).toHaveValue('Test User');
  await expect(page.getByRole('spinbutton', { name: 'Hours' })).toHaveValue('');
});

test('reuses the requestId when an uncertain submission is retried', async ({
  page,
}) => {
  await installMocks(page, '```json\n{"entries":[\n```');
  await page.goto('/');
  const input = await readyComposer(page);
  await input.fill('Capture manually');
  await page.getByRole('button', { name: /send/i }).click();
  await expect(
    page.getByRole('heading', { name: 'Manual Timesheet Review' })
  ).toBeVisible();

  await page.getByLabel('Project ID (optional)').fill('PRJ-1');
  await page.getByLabel('Project number').fill('PA-1');
  await page.getByLabel('Project name').fill('Operations');
  await page.getByLabel('Work order').fill('WO-1');
  await page.getByLabel('Task details').fill('Manual task');
  await page.getByRole('spinbutton', { name: 'Hours' }).fill('1');
  await page.getByLabel('Start time (optional)').fill('09:00');
  await page.getByLabel('Stop time (optional)').fill('10:00');
  await page.getByLabel('Payroll time type').fill('Regular');
  await page.getByLabel('Expenditure type').fill('Regular Time');

  const requests: Array<{
    entries: Array<{ requestId?: string }>;
  }> = [];
  let attempts = 0;
  await page.route(
    (url) => url.pathname === '/api/otl/timecard',
    async (route: Route) => {
      attempts += 1;
      requests.push(
        route.request().postDataJSON() as {
          entries: Array<{ requestId?: string }>;
        }
      );
      if (attempts === 1) {
        await route.fulfill({
          status: 503,
          json: { detail: 'Oracle temporarily unavailable' },
        });
        return;
      }
      await route.fulfill({
        json: {
          submitted: 1,
          succeeded: 1,
          failed: 0,
          results: [{ index: 0, ok: true, id: 9001 }],
        },
      });
    }
  );

  await page.getByRole('button', { name: 'Approve & Submit' }).click();
  await expect(page.getByText('Oracle temporarily unavailable')).toBeVisible();
  await page.getByRole('button', { name: 'Retry submission safely' }).click();

  await expect(
    page.getByText('Server Confirmed', { exact: true })
  ).toBeVisible();
  await expect(
    page.getByText(/Server confirmed 1 of 1 timecards/i)
  ).toBeVisible();
  expect(requests).toHaveLength(2);
  expect(requests[0].entries[0].requestId).toBeTruthy();
  expect(requests[1].entries[0].requestId).toBe(
    requests[0].entries[0].requestId
  );
});
