import { expect, test } from '@playwright/test';

// story id → viewport. Ids follow src/stories/StateCatalogue.stories.tsx.
const FRAMES: [string, number, number][] = [
  ['overview-desktop', 1440, 960], ['holdings-drawer', 1440, 960], ['orders-pending', 1440, 960], ['compliance-cards', 1440, 960],
  ['stale', 1440, 960], ['stale-health', 1440, 960], ['loading', 1440, 960], ['empty', 1440, 960], ['error-broker', 1440, 960],
  ['light', 1440, 960], ['live', 1440, 960], ['tablet', 1024, 768], ['paused', 1440, 960], ['held', 1440, 960], ['halted', 1440, 960],
  ['stopped', 1440, 960], ['viewer', 1440, 960], ['api-down', 1440, 960],
  ['phone-overview', 390, 844], ['phone-holdings', 390, 844], ['phone-detail', 390, 844], ['phone-orders', 390, 844],
];

for (const [id, width, height] of FRAMES) {
  test(id, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.setViewportSize({ width, height });
    await page.goto('http://localhost:6106/iframe.html?viewMode=story&id=state-catalogue--' + id);
    // The Loading frame holds its requests open, so wait for the shell, not network idle.
    await page.locator('.nafa.app').waitFor();
    await page.waitForTimeout(1500);
    expect(errors).toEqual([]);
    await expect(page).toHaveScreenshot(id + '.png');
  });
}
