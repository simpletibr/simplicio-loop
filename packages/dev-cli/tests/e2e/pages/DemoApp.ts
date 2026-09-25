import { pathToFileURL } from 'node:url';
import * as path from 'node:path';
import { expect, type Locator, type Page } from '@playwright/test';

/**
 * Page Object for the bundled demo app (tests/e2e/fixtures/demo-app/index.html).
 *
 * The demo is a self-contained single-file SPA loaded over file:// so the example
 * runs offline, with no dev server. For a real product, replace `url()` with the
 * app's BASE_URL and keep the same role/label-based selectors.
 */
export class DemoApp {
  readonly page: Page;
  readonly emailInput: Locator;
  readonly passwordInput: Locator;
  readonly submitButton: Locator;
  readonly loginError: Locator;

  constructor(page: Page) {
    this.page = page;
    this.emailInput = page.getByLabel('E-mail');
    this.passwordInput = page.getByLabel('Senha');
    this.submitButton = page.getByRole('button', { name: 'Entrar' });
    this.loginError = page.getByTestId('login-error');
  }

  static url(): string {
    const file = path.resolve(__dirname, '..', 'fixtures', 'demo-app', 'index.html');
    return pathToFileURL(file).href;
  }

  async goto(): Promise<void> {
    await this.page.goto(DemoApp.url());
    await expect(this.page.getByRole('heading', { name: 'Entrar' })).toBeVisible();
  }

  async login(email: string, password: string): Promise<void> {
    await this.emailInput.fill(email);
    await this.passwordInput.fill(password);
    await this.submitButton.click();
  }

  async openReports(): Promise<void> {
    await this.page.getByRole('button', { name: 'Relatórios' }).click();
  }
}
