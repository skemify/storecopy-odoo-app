{
    "name": "StoreCopy Migration",
    "version": "17.0.1.1.0",
    "category": "Sales/Sales",
    "summary": "Connect Odoo to StoreCopy without passwords and migrate your store or CRM to or from Shopify, WooCommerce, Wix, HubSpot, ActiveCampaign, Pipedrive and more",
    "description": """
Connect Odoo to StoreCopy in one click, from Odoo or from storecopy.com, without typing a password or API key.
Migrate your e-commerce catalog, customers, orders and coupons to or from Shopify, WooCommerce, Wix, Squarespace,
Square Online, PrestaShop, Magento, Shopware, OpenCart, GoDaddy and Tiendanube, and your CRM contacts, companies,
deals and activities to HubSpot, ActiveCampaign, Pipedrive or Zoho CRM.
""",
    "author": "StoreCopy",
    "website": "https://storecopy.com/services",
    "support": "support@storecopy.com",
    "license": "LGPL-3",
    "depends": ["base", "web"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_config_parameter.xml",
        "views/storecopy_connection_views.xml",
        "views/authorize_templates.xml",
    ],
    "images": ["static/description/banner.png"],
    "installable": True,
    "application": True,
    "auto_install": False,
    "uninstall_hook": "uninstall_hook",
}
