# NAFA Console: web UI

This folder is the React port of the Claude Design prototype (the docs/09c
hand-off, kept locally and not committed), milestones **M0–M3**. It runs
against the real API in `../api`, or against a mocked API.

## Run it

You need Node 20+.

```sh
npm install
npm run dev          # http://localhost:5173, /api proxied to the real console API on :8080 (../api)
npm run dev:mock     # same UI, API mocked by MSW with the prototype fixtures
npm test             # Vitest: selector unit tests + app flow tests (73)
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

Playwright snapshots every frame of the state catalogue (44), including the
confirm modal steps, "Not applied" and the resume preflight, which it opens
by clicking (`e2e/frames.spec.ts`).

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
| `src/domain/` | Pure selectors ported from the prototype's `vmX()` view models: `core` (pill, timeline, Sharia card, confidence, nearest exit, pending lifecycle), `chrome`, `overview`, `holdings`, `orders`, `compliance`, `health`, `roadmap`, `controls`, `performance` (also Agent). Unit-tested in `domain.test.ts` and `desk.test.ts`. |
| `src/app/` | Shell (top bar, banners, nav, rail, phone tab bar), app context, routes, ⌘K palette, sign-in, the confirm modal and preflight, mock-scenario panel |
| `src/screens/` | Overview, Holdings (+ drawer), Orders, Compliance, Health, Roadmap, Controls, Audit, Performance, Alerts, Agent, Settings, More |
| `src/components/` | Shared components from the component sheet, icons, and ECharts charts. Equity and drawdown share one crosshair. |
| `src/glossary/` | `terms.ts`: a plain-English explanation of every term and abbreviation. `Term.tsx`: `<T k="atr">ATR</T>` for one term, and `<Gloss text>` to find terms inside free text such as order reasons. |
| `src/styles/nafa.css` | The prototype stylesheet, verbatim from docs/09b. Components use its class names, so spacing and states match the prototype. |
| `src/mocks/` | MSW handlers; `scenario.ts` builds every read payload from `sample-data.json` for each environment × data × trading × role, `desk.ts` the M1–M3 ones (preview/apply mutate the scenario) |
| `src/stories/` | Storybook state catalogue (HANDOFF §5) |

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

## Limits

* **Dates come from the server:** every date and count in the copy comes
  from `system.facts`, so no copy hard-codes a date.
* **Pending until the data exists:** confidence and stops need an insights
  file; account columns, slippage and drift need the paper account. The API
  returns null and the UI says pending; nothing is estimated.
* **No optimistic updates:** a control shows Applied only after every server
  step succeeded, and the screens refetch from the server afterwards.
