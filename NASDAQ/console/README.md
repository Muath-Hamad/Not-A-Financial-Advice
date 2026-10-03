# NAFA Operations Console

The private web dashboard for the live harness, to run on the Unraid tower.
Design documents:

* [docs/08](../docs/08-console-system-design.md): system design
* [docs/09](../docs/09-console-ui-spec.md): UI spec
* the Claude Design prototype hand-off, kept locally in `docs/09c` (not
  committed)

| Path | What | Status |
|---|---|---|
| `web/` | React + TypeScript + Vite UI (Tailwind, TanStack Query/Table, ECharts) | **M0–M3 done**: Overview, Holdings, Orders, Compliance, Health, Roadmap, Glossary, Controls with the 4-step confirm and resume preflight, Audit, Performance, Alerts, Agent, sign-in |
| `api/` | FastAPI API, ledger indexer, SQLite (alerts, auth, control events), control service, broker gateway | **M0–M3 done**: reads from the real ledger, sign-in with TOTP, preview/apply, audit, account book, ntfy, analytics |
| `Dockerfile`, `docker-entrypoint.sh` | The `nafa-console` image: Node build stage, then Python | written, not yet test-built |
| `unraid/nafa-console.xml` | Unraid Docker template | written |

The console is separate from the executor:

* It never holds broker keys: the separate gateway does.
* It changes trading only through `live/controls.json` commits (and the
  gateway's cancel/flatten commands); the harness re-reads controls at every
  step.
* If it goes down, trading is unaffected (docs/08 §3, §11).

## Run it locally

```sh
cd web && npm install && npm run build          # the UI
cd ../api && python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
CONSOLE_AUTH=off .venv/Scripts/python -m uvicorn nafa_console.app:app --port 8080   # or add a user first (api/README.md)
# http://localhost:8080 shows the real ledger of this checkout
```

For UI work without the API, run `cd web && npm run dev:mock`. That serves
the prototype fixtures through MSW, with a scenario switcher.

## On the Unraid box

1. Build the image:
   ```sh
   git clone <repo> && docker build -t nafa-console <repo>/NASDAQ/console
   ```
2. Copy `unraid/nafa-console.xml` to `/boot/config/plugins/dockerMan/templates-user/`.
3. Add the container from that template.
4. Set **Ledger repository** to the repository's HTTPS URL.
5. Map the port to the LAN or Tailscale address only.

On first start the container clones the ledger into
`/mnt/user/appdata/nafa-console/repo`. It then pulls it every minute.

## Every term explained

Any dotted-underlined word or abbreviation shows a plain-English card when
you hover it, focus it or tap it (`web/src/glossary/`). **Glossary** in the
nav lists them all.

## Milestones (docs/08 §12)

* **M0, read-only:** done. The Unraid image is written; test-build it on
  the box.
* **M1, controls:** done. Controls screen, the 4-step confirm modal
  (impact → reason → TOTP → result), resume preflight, sign-in with TOTP,
  Audit log, and the harness changes in docs/08 §7.2 (`controls.json` v2).
  Control writes default to a dry run; set `CONSOLE_WRITE=git` on the box.
* **M2, account:** done. Paper broker gateway, Account book, fills and
  slippage, drift, `live-control.yml`, the Alerts inbox with ntfy, and
  Performance.
* **M3, insights:** done. `live/insights.py` runs in Cycle A and writes
  confidence, stops and regime; `live/calibration.py` writes the OOS
  calibration; Agent screen; monthly review pack. Confidence shows as
  pending until the first successful Cycle A after this change.
