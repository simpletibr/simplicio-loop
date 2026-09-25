/*
 * Example: how Playwright tests a frontend flow and produces PR evidence.
 *
 * Playwright drives a real browser against the rendered UI, so it works the same
 * regardless of the frontend language/framework (React, Vue, Angular, Blazor,
 * plain HTML...). It does not read the frontend source — it clicks, types,
 * navigates and asserts what the user actually sees.
 *
 * This spec exercises the bundled offline demo app. To test a real product,
 * swap DemoApp for your own page objects and point them at BASE_URL.
 *
 * Evidence policy here: screenshots only (per the current request). Each screen
 * is saved as a stable PNG under docs/evidence/frontend-flow/ so it shows up in
 * the PR diff, and is also attached to the Playwright HTML report.
 */

import * as path from 'node:path';
import { expect, test, type Page, type TestInfo } from '@playwright/test';
import { DemoApp } from './pages/DemoApp';

const EVIDENCE_DIR = path.resolve(__dirname, '..', '..', 'docs', 'evidence', 'frontend-flow');

async function capture(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  const file = path.join(EVIDENCE_DIR, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  await testInfo.attach(name, { path: file, contentType: 'image/png' });
}

test.describe('Frontend flow (demo app)', () => {
  let app: DemoApp;

  test.beforeEach(async ({ page }) => {
    app = new DemoApp(page);
    await app.goto();
  });

  test('happy path: login leads to dashboard and reports', async ({ page }, testInfo) => {
    await capture(page, testInfo, '01-login');

    await app.login('demo@simplicio.dev', 'senha123');

    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
    await expect(page.getByTestId('user-name')).toHaveText('demo@simplicio.dev');
    await expect(page.getByTestId('metric-done')).toHaveText('12');
    await capture(page, testInfo, '02-dashboard');

    await app.openReports();

    await expect(page.getByRole('heading', { name: 'Relatórios' })).toBeVisible();
    await expect(page.getByRole('row')).toHaveCount(3); // header + 2 data rows
    await expect(page.getByText('sprint-02')).toBeVisible();
    await capture(page, testInfo, '03-reports');
  });

  test('invalid credentials show an error and keep the user on login', async ({ page }, testInfo) => {
    await app.login('demo@simplicio.dev', 'wrong-password');

    await expect(app.loginError).toHaveText('Credenciais inválidas.');
    await expect(page.getByRole('heading', { name: 'Entrar' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toHaveCount(0);
    await capture(page, testInfo, '04-login-error');
  });
});
