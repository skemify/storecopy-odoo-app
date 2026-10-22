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
- **Reconnect** issues a new key and deletes the old one; **Disconnect** deletes the key.

## Lab

mig-lab mounts this repository into its Odoo docker (`/mnt/extra-addons`):

```bash
cd /Users/taras/gitnext/storecopy-mig
npm run odoo:app-install        # install or upgrade the module in mig_lab, run its tests
```

## Odoo Apps store

Register the repository's `17.0` branch on apps.odoo.com (Upload your apps → repository URL `…#17.0`). The listing
uses `static/description/index.html`, `icon.png` and `banner.png`.
