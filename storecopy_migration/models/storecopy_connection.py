import base64
import logging
from datetime import timedelta
from urllib.parse import quote, urlencode, urlparse

import requests

from odoo import _, api, fields, models, release
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

API_KEY_NAME = "StoreCopy migration"
TIMEOUT = 60
DISCONNECT_TIMEOUT = 15
ROTATE_BEFORE = timedelta(days=7)
LAB_HOSTS = ("localhost", "127.0.0.1", "host.docker.internal")


class StorecopyConnection(models.Model):
    """The link between this database and StoreCopy.

    Connecting creates an RPC API key for the user who connects (no extra Odoo seat) and registers the database with
    StoreCopy (POST <api_url>/api/install-odoo), either from this form or from the consent page storecopy.com sends the
    merchant to (/storecopy/authorize, with StoreCopy's signed state). StoreCopy checks the key by logging in over JSON-RPC, stores it
    encrypted and answers with the page that continues the migration, plus a pairing key that later connects and the
    disconnect send back to prove they come from this database. Disconnecting tells StoreCopy
    (POST <api_url>/api/odoo-disconnect) and deletes the key, which ends StoreCopy's access.
    """

    _name = "storecopy.connection"
    _description = "StoreCopy connection"

    name = fields.Char(default="StoreCopy", readonly=True)
    state = fields.Selection(
        [("disconnected", "Not connected"), ("connected", "Connected")],
        default="disconnected",
        required=True,
        readonly=True,
    )
    kind = fields.Selection(
        [("src", "Move this Odoo store to another platform"), ("dst", "Bring another store into this Odoo")],
        string="Migration",
        default="src",
        required=True,
    )
    odoo_url = fields.Char(
        string="Odoo URL",
        default=lambda self: self.env["ir.config_parameter"].sudo().get_param("web.base.url"),
        required=True,
        help="The public address StoreCopy uses to reach this Odoo over JSON-RPC.",
    )
    code = fields.Char(
        string="Pairing code",
        help="Only when you started on storecopy.com and it gave you a code; otherwise StoreCopy creates one.",
    )
    store_name = fields.Char(string="StoreCopy store", readonly=True)
    user_id = fields.Many2one("res.users", string="Connected as", readonly=True)
    api_key_id = fields.Integer(readonly=True)
    api_key_expires = fields.Datetime(string="API key expires", readonly=True)
    pairing_key = fields.Char(readonly=True, copy=False, groups="base.group_system")
    connected_at = fields.Datetime(readonly=True)
    last_error = fields.Text(readonly=True)

    @api.model
    def _api_url(self):
        return (self.env["ir.config_parameter"].sudo().get_param("storecopy_migration.api_url") or "https://storecopy.com").rstrip("/")

    @api.model
    def _api_host(self):
        return urlparse(self._api_url()).hostname or self._api_url()

    @api.model
    def _api_url_allowed(self):
        """https, or plain http to a StoreCopy running on this machine (the lab)."""
        url = self._api_url()
        return url.startswith("https://") or (url.startswith("http://") and urlparse(url).hostname in LAB_HOSTS)

    @api.model
    def _state_info(self, state):
        """The readable part of StoreCopy's signed state odoo|nonce|code|kind|expires|b64(url)|b64(database)|signature.

        Only for showing the consent page; StoreCopy checks the signature when the key comes back with the state.
        """
        parts = (state or "").split("|")
        if len(parts) != 8 or parts[0] != "odoo" or parts[3] not in ("src", "dst"):
            return None
        try:
            url = base64.urlsafe_b64decode(parts[5] + "=" * (-len(parts[5]) % 4)).decode()
        except ValueError:
            return None
        return {"code": parts[2], "kind": parts[3], "url": url}

    @api.model
    def action_open_connection(self):
        record = self.search([], limit=1) or self.create({})
        return {
            "type": "ir.actions.act_window",
            "name": _("StoreCopy Migration"),
            "res_model": self._name,
            "res_id": record.id,
            "view_mode": "form",
            "target": "current",
        }

    def _generate_api_key(self):
        """An RPC key of the current user, named so the user finds it under Account Security.

        Committed in its own cursor: StoreCopy logs in with it while this request is still open, and an uncommitted
        key does not exist for that login ("invalid credentials").
        """
        user = self.env.user
        if not user._is_internal():
            raise UserError(_("Only an internal user can connect StoreCopy."))
        return self._new_key(user)

    def _new_key(self, user, expiration=None):
        with self.env.registry.cursor() as cr:
            keys = self.env(cr=cr)["res.users.apikeys"].sudo()
            key = self._generate_for(keys.with_user(user), expiration)
            record = keys.search([("user_id", "=", user.id), ("name", "=", API_KEY_NAME)], order="id desc", limit=1)
            expires = record.expiration_date if "expiration_date" in record._fields else False
        return key, record.id, expires

    @api.model
    def _generate_for(self, keys, expiration):
        # None: a persistent key, which Odoo allows a system administrator; anyone else gets an expiry date.
        return keys._generate("rpc", API_KEY_NAME, expiration)

    def _delete_api_key(self, key_id):
        """In its own cursor too: a key committed after this request began is not visible to it."""
        if key_id:
            with self.env.registry.cursor() as cr:
                self.env(cr=cr)["res.users.apikeys"].sudo().browse(key_id).exists().unlink()

    def _revoke_api_key(self):
        self._delete_api_key(self.api_key_id)

    def _install_payload(self, key):
        company = self.env.company
        return {
            "url": (self.odoo_url or "").rstrip("/"),
            "database": self.env.cr.dbname,
            "login": self.env.user.login,
            "apiKey": key,
            "kind": self.kind,
            "code": (self.code or "").strip() or None,
            "pairingKey": self.sudo().pairing_key or None,
            "company": company.name,
            "email": company.email or self.env.user.email or None,
            "currency": company.currency_id.name,
            "odooVersion": release.version,
        }

    def _connect(self, state=None):
        """Creates the key, registers it with StoreCopy and records the connection; returns StoreCopy's answer.

        With `state` (the consent page), the Odoo URL and the pairing are the ones storecopy.com signed into it.
        """
        self.ensure_one()
        info = self._state_info(state) if state else None
        if state and not info:
            return {"ok": False, "error": _("This connect link is not valid. Start again on storecopy.com.")}
        if info:
            self.odoo_url = info["url"]
        elif not self.odoo_url or not self.odoo_url.startswith("https://"):
            raise UserError(_("Set the Odoo URL StoreCopy can reach over https (https://…). StoreCopy does not connect over plain http."))
        if not self._api_url_allowed():
            raise UserError(_("The StoreCopy address (system parameter storecopy_migration.api_url) must start with https://."))
        key, key_id, expires = self._generate_api_key()
        payload = self._install_payload(key)
        url = f"{self._api_url()}/api/install-odoo"
        if info:
            payload.update({"state": state, "code": None, "pairingKey": None, "kind": info["kind"]})
            url = f"{url}?state={quote(state, safe='')}"
        try:
            response = requests.post(url, json=payload, timeout=TIMEOUT)
            body = response.json() if response.content else {}
        except (requests.RequestException, ValueError) as err:
            body = {"ok": False, "error": str(err)}
        if not body.get("ok"):
            # Not raised: the transaction commits, so the unused key is gone and the error stays on the form.
            self._delete_api_key(key_id)
            body["error"] = body.get("error") or _("StoreCopy did not accept the connection.")
            self.last_error = body["error"]
            _logger.warning("StoreCopy connect failed: %s", body["error"])
            return body
        self._revoke_api_key()
        self.write(
            {
                "state": "connected",
                "code": body.get("code"),
                "kind": body.get("kind") or self.kind,
                "store_name": body.get("store"),
                "user_id": self.env.user.id,
                "api_key_id": key_id,
                "api_key_expires": expires,
                "pairing_key": body.get("pairingKey") or self.sudo().pairing_key,
                "connected_at": fields.Datetime.now(),
                "last_error": False,
            }
        )
        return body

    def action_connect(self):
        self.ensure_one()
        body = self._connect()
        if not body.get("ok"):
            error = body["error"]
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "type": "danger",
                    "title": _("StoreCopy could not connect"),
                    "message": error,
                    "sticky": True,
                    "next": {"type": "ir.actions.act_window_close"},
                },
            }
        return self._open_url(body.get("redirect"))

    def action_open_storecopy(self):
        self.ensure_one()
        params = urlencode({"platform": "odoo", "code": self.code or "", "kind": self.kind, "store": self.store_name or ""})
        return self._open_url(f"{self._api_url()}/app?{params}")

    def _notify_disconnect(self):
        """Best effort: StoreCopy may be unreachable, and the local disconnect goes ahead anyway."""
        api_url = self._api_url()
        if self.state != "connected" or not self.code or not self._api_url_allowed():
            return
        payload = {"code": self.code, "kind": self.kind, "store": self.store_name, "pairingKey": self.sudo().pairing_key or None}
        try:
            response = requests.post(f"{api_url}/api/odoo-disconnect?{urlencode({'code': self.code})}", json=payload, timeout=DISCONNECT_TIMEOUT)
            body = response.json() if response.content else {}
        except (requests.RequestException, ValueError) as err:
            body = {"ok": False, "error": str(err)}
        if not body.get("ok"):
            _logger.warning("StoreCopy disconnect notice failed for %s: %s", self.code, body.get("error") or body)

    def action_disconnect(self):
        self.ensure_one()
        self._notify_disconnect()
        self._revoke_api_key()
        self.write(
            {
                "state": "disconnected",
                "api_key_id": 0,
                "api_key_expires": False,
                "connected_at": False,
                "store_name": False,
                "code": False,
                "pairing_key": False,
            }
        )
        return True

    @api.model
    def _cron_rotate_keys(self):
        """Odoo 18+ caps a non-administrator's key; a week before it expires, hand StoreCopy a new one."""
        due = self.search([("state", "=", "connected"), ("api_key_expires", "!=", False), ("api_key_expires", "<", fields.Datetime.now() + ROTATE_BEFORE)])
        for connection in due:
            connection._rotate_key()

    def _rotate_key(self):
        self.ensure_one()
        user = self.user_id
        if not user or not user.active or not self._api_url_allowed():
            return False
        old = self.env["res.users.apikeys"].sudo().browse(self.api_key_id).exists()
        lifetime = (old.expiration_date - old.create_date) if old and "expiration_date" in old._fields and old.expiration_date else None
        key, key_id, expires = self._new_key(user, fields.Datetime.now() + lifetime if lifetime else None)
        payload = {"code": self.code, "store": self.store_name, "pairingKey": self.sudo().pairing_key or None, "apiKey": key}
        try:
            response = requests.post(f"{self._api_url()}/api/odoo-rotate?{urlencode({'code': self.code})}", json=payload, timeout=TIMEOUT)
            body = response.json() if response.content else {}
        except (requests.RequestException, ValueError) as err:
            body = {"ok": False, "error": str(err)}
        if not body.get("ok"):
            self._delete_api_key(key_id)
            self.last_error = body.get("error") or _("StoreCopy did not accept the new API key.")
            _logger.warning("StoreCopy key rotation failed for %s: %s", self.store_name, self.last_error)
            return False
        self._revoke_api_key()
        self.write({"api_key_id": key_id, "api_key_expires": expires, "last_error": False})
        return True

    def _open_url(self, url):
        if not url:
            return True
        return {"type": "ir.actions.act_url", "url": url, "target": "new"}
