from urllib.parse import urlencode

from odoo import http, release
from odoo.http import request


class StorecopyController(http.Controller):
    @http.route("/storecopy/info", type="http", auth="public", methods=["GET"], csrf=False)
    def info(self):
        """Lets storecopy.com see that the module is installed before it sends the merchant to the consent page."""
        module = request.env["ir.module.module"].sudo().search([("name", "=", "storecopy_migration")], limit=1)
        return request.make_json_response(
            {"module": "storecopy_migration", "version": module.latest_version or "", "odoo": release.version, "db": request.db}
        )

    @http.route("/storecopy/authorize", type="http", auth="user", methods=["GET"], website=True, sitemap=False)
    def authorize(self, state=None, **kwargs):
        """The consent page storecopy.com sends the merchant to, like an OAuth authorize screen."""
        connection = request.env["storecopy.connection"]
        values = {
            "state": state or "",
            "request_info": connection._state_info(state),
            "user": request.env.user,
            "db": request.db,
            "storecopy_host": connection._api_host(),
            "allowed": request.env.user.has_group("base.group_system"),
            "error": kwargs.get("error"),
        }
        return request.render("storecopy_migration.authorize_page", values)

    @http.route("/storecopy/authorize", type="http", auth="user", methods=["POST"], website=True, sitemap=False)
    def authorize_decision(self, state=None, decision=None, **kwargs):
        connection_model = request.env["storecopy.connection"]
        if decision != "allow":
            return request.redirect(f"{connection_model._api_url()}/app?{urlencode({'platform': 'odoo', 'error': 'access_denied'})}", local=False)
        if not request.env.user.has_group("base.group_system"):
            return self.authorize(state=state)
        connection = connection_model.search([], limit=1) or connection_model.create({})
        result = connection._connect(state=state)
        if not result.get("ok"):
            return self.authorize(state=state, error=result.get("error"))
        return request.redirect(result.get("redirect") or f"{connection_model._api_url()}/app", local=False)
