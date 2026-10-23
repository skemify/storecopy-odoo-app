{
    "name": "StoreCopy Migration",
    "version": "17.0.1.0.0",
    "category": "Sales/Sales",
    "summary": "Migrate products, categories, customers, orders and coupons between Odoo and Shopify, WooCommerce, Wix and other e-commerce platforms",
    "description": """
Connect Odoo to StoreCopy in one click and migrate your e-commerce catalog, customers, orders and coupons
to or from Shopify, WooCommerce, Wix, Squarespace, Square Online, PrestaShop, Magento, Shopware, OpenCart,
GoDaddy and Tiendanube. HubSpot: products, contacts and orders only.
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
