{
    "name": "StoreCopy Migration",
    "version": "17.0.1.0.0",
    "category": "Sales/Sales",
    "summary": "Move products, customers, orders and discounts between Odoo and Shopify, HubSpot, Wix, WooCommerce and 20+ platforms",
    "description": """
Connect Odoo to StoreCopy in one click and migrate your catalog, customers, orders and coupons
to or from Shopify, HubSpot, Wix, WooCommerce, Squarespace, PrestaShop, Magento and more.
""",
    "author": "StoreCopy",
    "website": "https://storecopy.com/services",
    "support": "support@storecopy.com",
    "license": "LGPL-3",
    "depends": ["base", "sale_management", "stock"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_config_parameter.xml",
        "views/storecopy_connection_views.xml",
    ],
    "images": ["static/description/banner.png"],
    "installable": True,
    "application": True,
    "auto_install": False,
}
