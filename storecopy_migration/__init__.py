from . import models
from .models.storecopy_connection import API_KEY_NAME


def uninstall_hook(env):
    """Tell StoreCopy about every connection, then delete every key the module created."""
    for connection in env["storecopy.connection"].sudo().search([("state", "=", "connected")]):
        connection._notify_disconnect()
    env["res.users.apikeys"].sudo().search([("name", "=", API_KEY_NAME)]).unlink()
