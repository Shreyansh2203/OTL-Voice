import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

const WORK_ORDERS = {
  employeeId: '7',
  fullName: 'Test User',
  workOrders: [
    {
      workOrder: 'WO-100',
      description: 'Operations',
      projects: [
        {
          projectId: 'PRJ-1',
          projectNo: 'PA-1',
          projectName: 'Apollo',
          tasks: [{ taskId: 'TASK-1', taskDetails: 'Verify payroll import' }],
        },
      ],
    },
  ],
};

const TIMECARDS = {
  items: [
    {
      timeRecordEvent: [
        {
          startTime: '2026-09-25T09:00:00Z',
          measure: 2.5,
          timeRecordEventAttribute: [
            { attributeName: 'PJC_PROJECT_NUMBER', attributeValue: 'PA-1' },
          ],
        },
      ],
    },
  ],
};

const REVIEW_REPLY =
  'Review before approval.\n```json\n' +
  JSON.stringify({
    entries: [
      {
        employeeNumber: '7',
        employeeName: 'Test User',
        projectId: 'PRJ-1',
        projectNo: 'PA-1',
        projectName: 'Apollo',
        workOrder: 'WO-100',
        taskDetails: 'Verify payroll import',
        hours: 2.5,
        date: '2026-09-25',
        startTime: '09:00',
        stopTime: '11:30',
        currencyCode: 'USD',
      },
    ],
  }) +
  '\n```';

async function mockApi(page: Page, signedIn: boolean): Promise<void> {
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === '/api/auth/session') {
        await route.fulfill(
          signedIn
            ? {
                json: { username: '7', fullName: 'Test User', employeeId: '7' },
              }
            : { status: 401, json: { detail: 'Session expired' } }
        );
        return;
      }
      if (path === '/api/auth/refresh') {
        await route.fulfill(
          signedIn
            ? { json: { ok: true } }
            : { status: 401, json: { detail: 'Session expired' } }
        );
        return;
      }
      if (path === '/api/health' || path === '/api/health/otl') {
        await route.fulfill({ json: { ok: true, status: 'connected' } });
        return;
      }
      if (path === '/api/chat') {
        // The workspace opens by asking the assistant to begin, so the kickoff
        // has to answer with the review payload for the form to exist.
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
        const delta = isKickoff ? REVIEW_REPLY : '';
        await route.fulfill({
          contentType: 'text/event-stream',
          body:
            `data: ${JSON.stringify({ delta })}\n\n` +
            `data: ${JSON.stringify({ done: true })}\n\n`,
        });
        return;
      }
      if (path === '/api/tts') {
        await route.fulfill({ status: 204, body: '' });
        return;
      }
      if (path === '/api/labour/assignments') {
        await route.fulfill({ json: WORK_ORDERS });
        return;
      }
      if (path === '/api/otl/timecards') {
        await route.fulfill({ json: TIMECARDS });
        return;
      }
      await route.fulfill({ status: 404, json: { detail: 'Not mocked' } });
    }
  );
}

async function scan(page: Page, label: string): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();
  expect(
    results.violations,
    `${label}: ${results.violations
      .map((v) => `${v.id} (${v.nodes.length} nodes) ${v.nodes[0]?.target}`)
      .join('; ')}`
  ).toEqual([]);
}

test.describe('accessibility', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('otl_voice_on', 'false');
    });
  });

  test('chat view has no detectable accessibility violations', async ({
    page,
  }) => {
    await mockApi(page, true);
    await page.goto('/');
    await expect(
      page.getByText('Review before approval.')
    ).toBeVisible();
    await page.waitForTimeout(500);

    await scan(page, 'chat tab at desktop width');
  });

  test('projects tab has no detectable accessibility violations', async ({
    page,
  }) => {
    await mockApi(page, true);
    await page.goto('/');
    await page
      .getByRole('button', { name: 'Navigate to Projects' })
      .click();

    // The search box used to be reachable only by its placeholder, which axe
    // does not accept as an accessible name.
    const search = page.getByRole('textbox', {
      name: /search by work order/i,
    });
    await expect(search).toBeVisible();
    await page.waitForTimeout(200);

    await scan(page, 'projects tab');

    await search.fill('apollo');
    await expect(page.getByText('Apollo').first()).toBeVisible();
    await scan(page, 'projects tab with an active search');
  });

  test('history tab has no detectable accessibility violations', async ({
    page,
  }) => {
    await mockApi(page, true);
    await page.goto('/');
    await page.getByRole('button', { name: 'Navigate to History' }).click();
    await expect(page.getByText('Recent Timecards')).toBeVisible();

    await scan(page, 'history tab');
  });

  test('timesheet review form has no detectable accessibility violations', async ({
    page,
  }) => {
    await mockApi(page, true);
    await page.goto('/');
    await expect(page.getByText('Review before approval.')).toBeVisible();
    const reviewPanel = page.locator('section.approval-card');
    await expect(page.getByText('Awaiting Approval')).toBeVisible();
    await expect(reviewPanel).toBeVisible();
    await expect(reviewPanel).toHaveAttribute('aria-label', 'Review Timesheet');
    const hours = reviewPanel.getByRole('spinbutton', { name: 'Hours' });
    await expect(hours).toBeVisible();
    await hours.focus();
    await expect(hours).toBeFocused();

    await scan(page, 'review form with a focused input');
  });

  test('chat view has no detectable accessibility violations on a phone', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockApi(page, true);
    await page.goto('/');
    await expect(
      page.getByText('Review before approval.')
    ).toBeVisible();
    await page.waitForTimeout(500);

    await scan(page, 'chat tab at phone width');
  });

  test('the open navigation drawer has no detectable accessibility violations', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockApi(page, true);
    await page.goto('/');
    const openNavigation = page.getByRole('button', { name: 'Open navigation' });
    await expect(openNavigation).toBeVisible();
    await openNavigation.click();
    await expect(
      page.getByRole('button', { name: 'Navigate to Projects' })
    ).toBeVisible();

    await scan(page, 'open navigation drawer');

    // The drawer is modal, so focus must be inside it and stay there.
    const drawer = page.locator('#primary-navigation');
    await expect(
      drawer.getByRole('button', { name: 'Close navigation' })
    ).toBeFocused();
  });

  test('sign-in view has no detectable accessibility violations', async ({
    page,
  }) => {
    await mockApi(page, false);
    await page.goto('/');
    await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible();
    await expect(page.getByLabel('Person number')).toBeFocused();

    await scan(page, 'sign-in view');
  });

  test('mobile sidebar is hidden until explicitly opened and closable', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockApi(page, true);
    await page.goto('/');
    const openNavigation = page.getByRole('button', { name: 'Open navigation' });
    const projects = page.getByRole('button', { name: 'Navigate to Projects' });

    await expect(openNavigation).toBeVisible();
    await expect(projects).toBeHidden();
    await openNavigation.click();
    await expect(projects).toBeVisible();
    await page
      .locator('#primary-navigation')
      .getByRole('button', { name: 'Close navigation' })
      .click();
    await expect(projects).toBeHidden();
  });
});
