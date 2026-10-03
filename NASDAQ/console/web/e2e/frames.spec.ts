import { expect, test } from '@playwright/test';

// story id → viewport. Ids follow src/stories/StateCatalogue.stories.tsx.
const FRAMES: [string, number, number][] = [
  ['overview-desktop', 1440, 960], ['holdings-drawer', 1440, 960], ['orders-pending', 1440, 960], ['compliance-cards', 1440, 960],
  ['stale', 1440, 960], ['stale-health', 1440, 960], ['loading', 1440, 960], ['empty', 1440, 960], ['error-broker', 1440, 960],
  ['light', 1440, 960], ['live', 1440, 960], ['tablet', 1024, 768], ['paused', 1440, 960], ['held', 1440, 960], ['halted', 1440, 960],
  ['stopped', 1440, 960], ['viewer', 1440, 960], ['api-down', 1440, 960],
  ['phone-overview', 390, 844], ['phone-holdings', 390, 844], ['phone-detail', 390, 844], ['phone-orders', 390, 844],
  ['controls-running', 1440, 960], ['controls-paused', 1440, 960], ['controls-held', 1440, 960], ['controls-halted', 1440, 960],
  ['controls-stopped', 1440, 960], ['audit', 1440, 960], ['performance-equity', 1440, 960], ['performance-returns', 1440, 960],
  ['performance-attribution', 1440, 960], ['performance-execution', 1440, 960], ['performance-ghost', 1440, 960], ['alerts', 1440, 960],
  ['agent', 1440, 960], ['sign-in', 1440, 960], ['phone-controls', 390, 844],
];

const story = (id: string) => 'http://localhost:6106/iframe.html?viewMode=story&id=state-catalogue--' + id;

for (const [id, width, height] of FRAMES) {
  test(id, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.setViewportSize({ width, height });
    await page.goto(story(id));
    // The Loading frame holds its requests open, so wait for the shell, not network idle.
    await page.locator('.nafa.app').waitFor();
    await page.waitForTimeout(1500);
    expect(errors).toEqual([]);
    await expect(page).toHaveScreenshot(id + '.png');
  });
}

// The confirm modal (HANDOFF §4.1–4.3) and the resume preflight, opened by clicks.
type Step = (p: import('@playwright/test').Page) => Promise<void>;
const dlg = (p: import('@playwright/test').Page) => p.getByRole('dialog');
const toReason: Step = async (p) => { await dlg(p).getByRole('button', { name: 'Continue' }).click(); };
const toVerify: Step = async (p) => {
  await toReason(p);
  await dlg(p).getByLabel(/Reason/).fill('Broker anomaly: unexpected open orders');
  await dlg(p).getByRole('button', { name: 'Continue' }).click();
};
const INTERACTIONS: [string, string, number, number, string, Step[]][] = [
  ['confirm-1-impact', 'controls-running', 1440, 960, 'STOP TRADING', []],
  ['confirm-2-reason', 'controls-running', 1440, 960, 'STOP TRADING', [toReason]],
  ['confirm-3-verify', 'controls-running', 1440, 960, 'STOP TRADING', [toVerify, async (p) => { await dlg(p).getByLabel(/Authenticator/).fill('123456'); await dlg(p).getByLabel(/^Type/).fill('STOP'); }]],
  ['confirm-4-applied', 'controls-running', 1440, 960, 'Pause entries', [toVerify, async (p) => {
    await dlg(p).getByLabel(/Authenticator/).fill('123456');
    await dlg(p).getByRole('button', { name: 'Pause entries' }).click();
    await dlg(p).getByText('Applied', { exact: true }).waitFor();
  }]],
  ['confirm-not-applied', 'controls-fail', 1440, 960, 'Pause entries', [toVerify, async (p) => {
    await dlg(p).getByLabel(/Authenticator/).fill('123456');
    await dlg(p).getByRole('button', { name: 'Pause entries' }).click();
    await dlg(p).getByText('Not applied', { exact: true }).waitFor();
  }]],
  ['preflight', 'controls-stopped', 1440, 960, 'Resume trading…', []],
  ['phone-confirm', 'phone-controls', 390, 844, 'STOP TRADING', []],
];

for (const [name, id, width, height, button, steps] of INTERACTIONS) {
  test(name, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.setViewportSize({ width, height });
    await page.goto(story(id));
    await page.locator('.nafa.app').waitFor();
    await page.getByRole('button', { name: button, exact: true }).click();
    await dlg(page).getByRole('button', { name: /Continue/ }).waitFor();
    await page.waitForTimeout(400);
    for (const s of steps) await s(page);
    await page.waitForTimeout(600);
    expect(errors).toEqual([]);
    await expect(page).toHaveScreenshot(name + '.png');
  });
}
