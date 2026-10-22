import logging

import requests

from odoo import _, api, fields, models, release
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

API_KEY_NAME = "StoreCopy migration"
TIMEOUT = 60


class StorecopyConnection(models.Model):
    """The link between this database and StoreCopy.

    Connecting creates an RPC API key for the user who connects (no extra Odoo seat) and registers the database with
    StoreCopy (POST <api_url>/api/install-odoo). StoreCopy checks the key by logging in over JSON-RPC, stores it
    encrypted and answers with the page that continues the migration. Disconnecting deletes the key, which ends
    StoreCopy's access.
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
    connected_at = fields.Datetime(readonly=True)
    last_error = fields.Text(readonly=True)

    @api.model
    def _api_url(self):
        return (self.env["ir.config_parameter"].sudo().get_param("storecopy_migration.api_url") or "https://storecopy.com").rstrip("/")

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
        """An RPC key of the current user, named so the user finds it under Account Security."""
        user = self.env.user
        if not user._is_internal():
            raise UserError(_("Only an internal user can connect StoreCopy."))
        keys = self.env["res.users.apikeys"].sudo()
        key = keys.with_user(user)._generate("rpc", API_KEY_NAME)
        key_id = keys.search([("user_id", "=", user.id), ("name", "=", API_KEY_NAME)], order="id desc", limit=1).id
        return key, key_id

    def _revoke_api_key(self):
        if self.api_key_id:
            self.env["res.users.apikeys"].sudo().browse(self.api_key_id).exists().unlink()

    def _install_payload(self, key):
        company = self.env.company
        return {
            "url": (self.odoo_url or "").rstrip("/"),
            "database": self.env.cr.dbname,
            "login": self.env.user.login,
            "apiKey": key,
            "kind": self.kind,
            "code": (self.code or "").strip() or None,
            "company": company.name,
            "email": company.email or self.env.user.email or None,
            "currency": company.currency_id.name,
            "odooVersion": release.version,
        }

    def action_connect(self):
        self.ensure_one()
        if not self.odoo_url or not self.odoo_url.startswith(("http://", "https://")):
            raise UserError(_("Set the Odoo URL StoreCopy can reach (https://…)."))
        key, key_id = self._generate_api_key()
        try:
            response = requests.post(f"{self._api_url()}/api/install-odoo", json=self._install_payload(key), timeout=TIMEOUT)
            body = response.json() if response.content else {}
        except (requests.RequestException, ValueError) as err:
            body = {"ok": False, "error": str(err)}
        if not body.get("ok"):
            # Not raised: the transaction commits, so the unused key is gone and the error stays on the form.
            self.env["res.users.apikeys"].sudo().browse(key_id).exists().unlink()
            error = body.get("error") or _("StoreCopy did not accept the connection.")
            self.last_error = error
            _logger.warning("StoreCopy connect failed: %s", error)
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
        self._revoke_api_key()
        self.write(
            {
                "state": "connected",
                "code": body.get("code"),
                "kind": body.get("kind") or self.kind,
                "store_name": body.get("store"),
                "user_id": self.env.user.id,
                "api_key_id": key_id,
                "connected_at": fields.Datetime.now(),
                "last_error": False,
            }
        )
        return self._open_url(body.get("redirect"))

    def action_open_storecopy(self):
        self.ensure_one()
        params = f"platform=odoo&code={self.code or ''}&kind={self.kind}&store={self.store_name or ''}"
        return self._open_url(f"https://storecopy.com/app?{params}")

    def action_disconnect(self):
        self.ensure_one()
        self._revoke_api_key()
        self.write({"state": "disconnected", "api_key_id": 0, "connected_at": False, "store_name": False, "code": False})
        return True

    def _open_url(self, url):
        if not url:
            return True
        return {"type": "ir.actions.act_url", "url": url, "target": "new"}
