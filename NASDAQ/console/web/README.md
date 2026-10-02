# NAFA Console: web UI

This folder is the React port of the Claude Design prototype
([docs/09c](../../docs/09c-console-prototype/HANDOFF.md)), milestone **M0
(read-only)**.

## Run it

You need Node 20+.

```sh
npm install
npm run dev:mock     # http://localhost:5173 with the API mocked by MSW (prototype fixtures)
npm run dev          # same, but /api is proxied to the console API on :8080
npm test             # Vitest: selector unit tests + app smoke tests (45)
npm run storybook    # state catalogue at http://localhost:6006
npm run build        # typecheck + production bundle in dist/
```

In mock mode:

* The **PROTOTYPE STATES** button at the bottom right switches the scenario:
  environment, data state, trading state, role, theme, and whether the API
  is down.
* You can deep-link a scenario, for example
  `/?mock.env=ghost&mock.data=stale` or `/orders?mock.trading=held&mock.role=viewer`.

## Visual tests

Playwright snapshots every M0 frame of the state catalogue
(`e2e/frames.spec.ts`).

```sh
npm run build-storybook
PW_CHANNEL=msedge npm run e2e:update   # first run on a machine: write baselines
PW_CHANNEL=msedge npm run e2e          # compare
```

Baselines depend on the platform, so they are git-ignored. Generate them on
the machine that runs the suite. `PW_CHANNEL` picks an installed browser;
leave it unset to use Playwright's own Chromium.

## Layout

| Path | What |
|---|---|
| `src/api/types.ts` | The v1 API contract (docs/08 §10), as TypeScript payloads. The FastAPI side must serve these shapes. |
| `src/api/client.ts` | One TanStack Query hook per endpoint. Polls every 60 s until SSE lands. |
| `src/domain/` | Pure selectors ported from the prototype's `vmX()` view models: `core` (pill, timeline, Sharia card, confidence, nearest exit, pending lifecycle), `chrome`, `overview`, `holdings`, `orders`, `compliance`, `health`, `roadmap`. Unit-tested in `domain.test.ts`. |
| `src/app/` | Shell (top bar, banners, nav, rail, phone tab bar), app context, routes, ⌘K palette, mock-scenario panel |
| `src/screens/` | Overview, Holdings (+ drawer), Orders, Compliance, Health, Roadmap, Settings, More, and placeholders for the M1/M2 screens |
| `src/components/` | Shared components from the component sheet, icons, and ECharts charts. Equity and drawdown share one crosshair. |
| `src/styles/nafa.css` | The prototype stylesheet, verbatim from docs/09b. Components use its class names, so spacing and states match the prototype. |
| `src/mocks/` | MSW handlers and `scenario.ts`, which builds every payload from `sample-data.json` for each environment × data × trading × role |
| `src/stories/` | Storybook state catalogue (HANDOFF §5), M0 frames |

## Rules kept from the prototype (HANDOFF §4)

* **Data age:** every panel shows how old its data is: amber after one
  session, red after two.
* **Books:** the Model and Account books are always labelled: a `MODEL`
  tag, and the Account book in violet.
* **Honest numbers:**
  * Missing Sharia data reads "Not available – licensed data pending".
  * Confidence always says "Model conviction, not a forecast."
* **Colour carries meaning:**
  * Green and red mean P&L sign only, and always come with a + or −.
  * Amber, red and blue mark severity.
  * The environment badge is GHOST dashed, PAPER blue, LIVE red with a top
    rule.
* **Viewer role:** no Controls nav, no row ⋯ menus, no action buttons.
* **Responsive breakpoints** are container queries on the app shell: nav ≥
  1280 px, rail 768–1279 px, tab bar and cards below 768 px.

## M0 limits

* **Read-only:** control buttons explain that controls arrive with M1. No
  modal, TOTP or preview/apply yet.
* **Placeholders:** Performance, Agent, Alerts and Audit are placeholder
  pages until their milestones. The equity chart and the open alerts already
  show in Overview and in the top bar.
* **Illustrative fixtures:** some copy still carries the fixture scenario's
  dates (for example "Mon 28 Sep" and "Cycle A failed 4×"). The API will
  supply these facts when the backend lands.
