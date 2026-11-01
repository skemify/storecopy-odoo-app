import base64
from datetime import timedelta
from unittest.mock import MagicMock, patch

from odoo.addons.storecopy_migration import uninstall_hook
from odoo.exceptions import UserError
from odoo import fields, http
from odoo.tests.common import HttpCase, TransactionCase, new_test_user, tagged

POST = "odoo.addons.storecopy_migration.models.storecopy_connection.requests.post"


def answer(body):
    response = MagicMock()
    response.content = b"{}"
    response.json.return_value = body
    return response


@tagged("post_install", "-at_install")
class TestStorecopyConnect(TransactionCase):
    def setUp(self):
        super().setUp()
        # The key is created and deleted in its own cursor; in test mode that cursor shares this test's transaction.
        self.registry.enter_test_mode(self.cr)
        self.addCleanup(self.registry.leave_test_mode)
        # An active internal administrator (the test superuser is inactive, so its keys never log in).
        self.env = self.env(user=self.env.ref("base.user_admin"))
        self.env["ir.config_parameter"].sudo().set_param("storecopy_migration.api_url", "https://sc.test/")
        self.connection = self.env["storecopy.connection"].create({"odoo_url": "https://odoo.example.com/", "kind": "src"})
        self.keys = self.env["res.users.apikeys"].sudo()
        self.earlier_keys = self._keys().ids

    def _keys(self):
        domain = [("user_id", "=", self.env.user.id), ("name", "=", "StoreCopy migration")]
        return self.keys.search(domain + [("id", "not in", getattr(self, "earlier_keys", []))])

    def test_connect_registers_the_database_with_a_new_key(self):
        reply = {"ok": True, "code": "c-1", "kind": "src", "store": "odoo.example.com", "redirect": "https://storecopy.com/api/pim/odoo?t=x"}
        with patch(POST, return_value=answer(reply)) as post:
            action = self.connection.action_connect()
        url = post.call_args.args[0]
        payload = post.call_args.kwargs["json"]
        self.assertEqual(url, "https://sc.test/api/install-odoo")
        self.assertEqual(payload["url"], "https://odoo.example.com")
        self.assertEqual(payload["database"], self.env.cr.dbname)
        self.assertEqual(payload["login"], self.env.user.login)
        self.assertEqual(payload["kind"], "src")
        self.assertTrue(payload["apiKey"])
        self.assertIsNone(payload["code"])
        self.assertEqual(self.connection.state, "connected")
        self.assertEqual(self.connection.store_name, "odoo.example.com")
        self.assertEqual(self.connection.code, "c-1")
        self.assertEqual(self._keys().ids, [self.connection.api_key_id])
        self.assertEqual(action, {"type": "ir.actions.act_url", "url": reply["redirect"], "target": "new"})
        # The key StoreCopy received logs in as this user.
        self.assertEqual(self.keys._check_credentials(scope="rpc", key=payload["apiKey"]), self.env.user.id)

    def test_refused_connection_leaves_no_key(self):
        with patch(POST, return_value=answer({"ok": False, "error": "StoreCopy could not reach https://odoo.example.com"})):
            action = self.connection.action_connect()
        self.assertEqual(action["params"]["type"], "danger")
        self.assertEqual(self.connection.state, "disconnected")
        self.assertIn("could not reach", self.connection.last_error)
        self.assertFalse(self._keys())

    def test_reconnect_replaces_the_key_and_disconnect_deletes_it(self):
        with patch(POST, return_value=answer({"ok": True, "code": "c-1", "store": "odoo.example.com"})):
            self.connection.action_connect()
            first = self.connection.api_key_id
            self.connection.action_connect()
        self.assertNotEqual(self.connection.api_key_id, first)
        self.assertEqual(self._keys().ids, [self.connection.api_key_id])
        with patch(POST, return_value=answer({"ok": True})):
            self.connection.action_disconnect()
        self.assertEqual(self.connection.state, "disconnected")
        self.assertFalse(self._keys())

    def test_unreachable_storecopy_leaves_no_key(self):
        with patch(POST, side_effect=__import__("requests").ConnectionError("connection refused")):
            self.connection.action_connect()
        self.assertEqual(self.connection.state, "disconnected")
        self.assertIn("connection refused", self.connection.last_error)
        self.assertFalse(self._keys())

    def test_url_is_required(self):
        self.connection.odoo_url = "odoo.example.com"
        with self.assertRaises(UserError):
            self.connection.action_connect()

    def test_open_connection_reuses_the_record(self):
        first = self.env["storecopy.connection"].action_open_connection()["res_id"]
        self.assertEqual(self.env["storecopy.connection"].action_open_connection()["res_id"], first)

    def test_http_odoo_url_is_refused(self):
        self.connection.odoo_url = "http://odoo.example.com"
        with patch(POST) as post, self.assertRaises(UserError):
            self.connection.action_connect()
        post.assert_not_called()
        self.assertFalse(self._keys())

    def test_http_storecopy_address_is_refused(self):
        self.env["ir.config_parameter"].sudo().set_param("storecopy_migration.api_url", "http://sc.test")
        with patch(POST) as post, self.assertRaises(UserError):
            self.connection.action_connect()
        post.assert_not_called()
        self.assertFalse(self._keys())

    def test_pairing_key_is_stored_and_sent_back_on_reconnect(self):
        reply = {"ok": True, "code": "c-1", "kind": "src", "store": "odoo.example.com", "pairingKey": "pk-1"}
        with patch(POST, return_value=answer(reply)) as post:
            self.connection.action_connect()
            self.assertIsNone(post.call_args.kwargs["json"]["pairingKey"])
            self.assertEqual(self.connection.pairing_key, "pk-1")
            self.connection.action_connect()
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["code"], "c-1")
        self.assertEqual(payload["pairingKey"], "pk-1")
        self.assertEqual(self.connection.pairing_key, "pk-1")

    def test_disconnect_tells_storecopy(self):
        reply = {"ok": True, "code": "c-1", "kind": "dst", "store": "odoo.example.com", "pairingKey": "pk-1"}
        with patch(POST, return_value=answer(reply)):
            self.connection.action_connect()
        with patch(POST, return_value=answer({"ok": True})) as post:
            self.connection.action_disconnect()
        self.assertEqual(post.call_args.args[0], "https://sc.test/api/odoo-disconnect?code=c-1")
        self.assertEqual(post.call_args.kwargs["json"], {"code": "c-1", "kind": "dst", "store": "odoo.example.com", "pairingKey": "pk-1"})
        self.assertEqual(self.connection.state, "disconnected")
        self.assertFalse(self.connection.pairing_key)
        self.assertFalse(self._keys())

    def test_unreachable_storecopy_does_not_block_disconnect(self):
        with patch(POST, return_value=answer({"ok": True, "code": "c-1", "store": "odoo.example.com", "pairingKey": "pk-1"})):
            self.connection.action_connect()
        with patch(POST, side_effect=__import__("requests").ConnectionError("connection refused")):
            self.connection.action_disconnect()
        self.assertEqual(self.connection.state, "disconnected")
        self.assertFalse(self._keys())

    def test_open_storecopy_uses_the_configured_address(self):
        self.connection.write({"state": "connected", "code": "c 1&x", "store_name": "odoo.example.com"})
        action = self.connection.action_open_storecopy()
        self.assertEqual(action["url"], "https://sc.test/app?platform=odoo&code=c+1%26x&kind=src&store=odoo.example.com")

    def test_uninstall_hook_tells_storecopy_and_deletes_the_keys(self):
        with patch(POST, return_value=answer({"ok": True, "code": "c-1", "store": "odoo.example.com", "pairingKey": "pk-1"})):
            self.connection.action_connect()
        self.assertTrue(self._keys())
        with patch(POST, return_value=answer({"ok": True})) as post:
            uninstall_hook(self.env)
        self.assertEqual(post.call_args.args[0], "https://sc.test/api/odoo-disconnect?code=c-1")
        self.assertEqual(post.call_args.kwargs["json"]["pairingKey"], "pk-1")
        self.assertFalse(self.keys.search([("name", "=", "StoreCopy migration")]))

    def _state(self, kind="dst", url="https://odoo.example.com"):
        b64 = lambda v: base64.urlsafe_b64encode(v.encode()).decode().rstrip("=")
        return f"odoo|n1|c-wiz|{kind}|9999999999|{b64(url)}|{b64(self.env.cr.dbname)}|sig"

    def test_consent_posts_the_key_with_the_state(self):
        state = self._state()
        reply = {"ok": True, "code": "c-wiz", "kind": "dst", "store": "odoo.example.com", "pairingKey": "pk-w", "redirect": "https://storecopy.com/app?code=c-wiz"}
        with patch(POST, return_value=answer(reply)) as post:
            body = self.connection._connect(state=state)
        self.assertEqual(body["redirect"], reply["redirect"])
        self.assertTrue(post.call_args.args[0].startswith("https://sc.test/api/install-odoo?state=odoo%7Cn1%7Cc-wiz%7Cdst"))
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["state"], state)
        self.assertEqual(payload["kind"], "dst")
        self.assertIsNone(payload["code"])
        self.assertEqual(payload["database"], self.env.cr.dbname)
        self.assertEqual((self.connection.state, self.connection.kind, self.connection.code, self.connection.pairing_key), ("connected", "dst", "c-wiz", "pk-w"))
        self.assertEqual(self._keys().ids, [self.connection.api_key_id])

    def test_consent_state_sets_the_url_even_over_http(self):
        with patch(POST, return_value=answer({"ok": False, "error": "nope"})) as post:
            body = self.connection._connect(state=self._state(url="http://localhost:9075"))
        self.assertEqual(post.call_args.kwargs["json"]["url"], "http://localhost:9075")
        self.assertEqual(body["error"], "nope")
        self.assertFalse(self._keys())

    def test_unreadable_state_posts_nothing(self):
        with patch(POST) as post:
            body = self.connection._connect(state="odoo|x")
        post.assert_not_called()
        self.assertFalse(body["ok"])
        self.assertFalse(self._keys())

    def test_storecopy_on_this_machine_may_use_http(self):
        self.env["ir.config_parameter"].sudo().set_param("storecopy_migration.api_url", "http://host.docker.internal:9000")
        self.assertTrue(self.env["storecopy.connection"]._api_url_allowed())
        self.env["ir.config_parameter"].sudo().set_param("storecopy_migration.api_url", "http://sc.test")
        self.assertFalse(self.env["storecopy.connection"]._api_url_allowed())

    def test_rotation_hands_storecopy_a_new_key_and_deletes_the_old(self):
        with patch(POST, return_value=answer({"ok": True, "code": "c-1", "store": "odoo.example.com", "pairingKey": "pk-1"})):
            self.connection.action_connect()
        first = self.connection.api_key_id
        self.connection.api_key_expires = fields.Datetime.now() + timedelta(days=2)
        with patch(POST, return_value=answer({"ok": True})) as post:
            self.env["storecopy.connection"]._cron_rotate_keys()
        self.assertEqual(post.call_args.args[0], "https://sc.test/api/odoo-rotate?code=c-1")
        payload = post.call_args.kwargs["json"]
        self.assertEqual((payload["code"], payload["store"], payload["pairingKey"]), ("c-1", "odoo.example.com", "pk-1"))
        self.assertEqual(self.keys._check_credentials(scope="rpc", key=payload["apiKey"]), self.env.user.id)
        self.assertNotEqual(self.connection.api_key_id, first)
        self.assertEqual(self._keys().ids, [self.connection.api_key_id])

    def test_refused_rotation_keeps_the_old_key(self):
        with patch(POST, return_value=answer({"ok": True, "code": "c-1", "store": "odoo.example.com", "pairingKey": "pk-1"})):
            self.connection.action_connect()
        first = self.connection.api_key_id
        self.connection.api_key_expires = fields.Datetime.now() + timedelta(days=2)
        with patch(POST, return_value=answer({"ok": False, "error": "login failed"})):
            self.env["storecopy.connection"]._cron_rotate_keys()
        self.assertEqual(self._keys().ids, [first])
        self.assertEqual(self.connection.last_error, "login failed")


@tagged("post_install", "-at_install")
class TestStorecopyConsentPage(HttpCase):
    def setUp(self):
        super().setUp()
        # Lab databases keep their own admin password, so the page is opened by a test administrator.
        new_test_user(self.env, login="sc_consent_admin", password="sc_consent_admin", groups="base.group_user,base.group_system")

    def _state(self):
        b64 = lambda v: base64.urlsafe_b64encode(v.encode()).decode().rstrip("=")
        return f"odoo|n1|c-wiz|src|9999999999|{b64('https://odoo.example.com')}|{b64(self.env.cr.dbname)}|sig"

    def test_info_tells_storecopy_the_module_is_installed(self):
        response = self.url_open("/storecopy/info")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["module"], "storecopy_migration")
        self.assertEqual(response.json()["db"], self.env.cr.dbname)

    def test_consent_page_needs_a_login(self):
        response = self.url_open(f"/storecopy/authorize?state={self._state()}", allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.assertIn("/web/login", response.headers["Location"])

    def test_consent_page_names_the_user_and_the_database(self):
        self.authenticate("sc_consent_admin", "sc_consent_admin")
        response = self.url_open(f"/storecopy/authorize?state={self._state()}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Allow", response.text)
        self.assertIn(self.env.cr.dbname, response.text)
        self.assertIn("this Odoo to another platform", response.text)

    def test_cancel_returns_to_storecopy(self):
        self.env["ir.config_parameter"].sudo().set_param("storecopy_migration.api_url", "https://sc.test")
        self.authenticate("sc_consent_admin", "sc_consent_admin")
        response = self.url_open(
            "/storecopy/authorize",
            data={"state": self._state(), "decision": "cancel", "csrf_token": http.Request.csrf_token(self)},
            allow_redirects=False,
        )
        self.assertIn(response.status_code, (302, 303))
        self.assertEqual(response.headers["Location"], "https://sc.test/app?platform=odoo&error=access_denied")

