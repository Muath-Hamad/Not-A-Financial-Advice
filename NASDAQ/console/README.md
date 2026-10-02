# NAFA Operations Console

The private web dashboard for the live harness, to run on the Unraid tower.
Design documents:

* [docs/08](../docs/08-console-system-design.md): system design
* [docs/09](../docs/09-console-ui-spec.md): UI spec
* the Claude Design prototype hand-off, kept locally in `docs/09c` (not
  committed)

| Path | What | Status |
|---|---|---|
| `web/` | React + TypeScript + Vite UI (Tailwind, TanStack Query/Table, ECharts) | **M0 done**: Overview, Holdings with detail, Orders, Compliance, Health, Roadmap, Glossary |
| `api/` | FastAPI read API, ledger indexer, SQLite (acknowledgements), serves the UI | **M0 done**: every read endpoint, from the real ledger |
| `Dockerfile`, `docker-entrypoint.sh` | The `nafa-console` image: Node build stage, then Python | written, not yet test-built |
| `unraid/nafa-console.xml` | Unraid Docker template | written |

The console is separate from the executor:

* It never holds broker keys in M0.
* It only reads the ledger.
* If it goes down, trading is unaffected (docs/08 §3, §11).

## Run it locally

```sh
cd web && npm install && npm run build          # the UI
cd ../api && python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/python -m uvicorn nafa_console.app:app --port 8080
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

* **M0, read-only:**
  * UI and API: done.
  * Unraid image: written; test-build it on the box.
* **M3, insights:** this step fills confidence ratings, stop levels and live
  prices (`live/ledger/insights/<asof>.json`, see `api/README.md`). Until
  then the console shows them as pending.
* **M1, controls:** the Controls screen, the 4-step confirm modal, the
  resume preflight, login with TOTP, the Audit log, and the harness changes
  in docs/08 §7.2.
* **M2, account:** the paper broker gateway, the Account book, fills and
  slippage, drift, the Alerts inbox with ntfy, and Performance.
