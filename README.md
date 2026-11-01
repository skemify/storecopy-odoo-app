# StoreCopy Migration for Odoo

Odoo app (`storecopy_migration`, Odoo 17.0) that connects an Odoo database to StoreCopy for migrations to and from
Shopify, HubSpot, Wix, WooCommerce and the other StoreCopy platforms. One branch per Odoo version, as the Odoo Apps
store expects (`17.0`), with the module at the repository root.

## What it does

- Menu **StoreCopy** (Settings administrators): direction (Odoo as source or destination), optional pairing code from
  storecopy.com, the Odoo URL StoreCopy should use (default `web.base.url`).
- **Connect to StoreCopy** creates an RPC API key "StoreCopy migration" for the connecting user (no extra Odoo seat)
  and posts `{url, database, login, apiKey, kind, code?, company, email, currency, odooVersion}` to
  `<storecopy_migration.api_url>/api/install-odoo` (system parameter, default `https://storecopy.com`). storecopy-back
  logs in with the key over JSON-RPC, stores it encrypted as store `<odoo host>`, pairs it and answers
  `{ok, code, kind, store, redirect}`; the app opens `redirect` (the signed-in wizard on storecopy.com).
- **From storecopy.com** (since 1.1.0): the wizard asks only for the Odoo address, storecopy-back checks
  `GET /storecopy/info` and sends the merchant to `/storecopy/authorize?state=…`, a consent page (Settings
  administrators) whose **Allow** creates the key and posts it to `/api/install-odoo` with StoreCopy's signed state,
  then returns to the wizard. The form's pairing code also takes the wizard's connect code `<code>.<pairingKey>`.
- **Reconnect** issues a new key and deletes the old one; **Disconnect** deletes the key. On 18/19 a daily cron hands
  StoreCopy a new key a week before an expiring key runs out (`POST /api/odoo-rotate`); administrators' keys don't expire.
- Depends on `base` and `web` only, so a CRM-only database can install it; storecopy.com checks the apps a route needs.
- The StoreCopy address must be https, except a StoreCopy on `localhost` / `host.docker.internal` (the lab).

## Lab

mig-lab mounts this repository into its Odoo docker (`/mnt/extra-addons`):

```bash
cd /Users/taras/gitnext/storecopy-mig
npm run odoo:app-install        # install or upgrade the module in mig_lab, run its tests
```

## Odoo Apps store

Register the repository's `17.0` branch on apps.odoo.com (Upload your apps → repository URL `…#17.0`). The listing
uses `static/description/index.html`, `icon.png` and `banner.png`.
