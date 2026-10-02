import { defineConfig } from '@playwright/test';

// Visual tests over the Storybook state catalogue (docs/09c HANDOFF §5).
// `npm run build-storybook` first; baselines live next to the spec.
// PW_CHANNEL=msedge (or chrome) uses an installed browser instead of a download.
export default defineConfig({
  testDir: 'e2e',
  snapshotPathTemplate: '{testDir}/__screenshots__/{arg}{ext}',
  use: { channel: process.env.PW_CHANNEL || undefined },
  expect: { toHaveScreenshot: { maxDiffPixelRatio: 0.01, animations: 'disabled' } },
  webServer: {
    command: 'node node_modules/http-server/bin/http-server storybook-static -p 6106 -s',
    url: 'http://localhost:6106/iframe.html',
    reuseExistingServer: true,
  },
});
