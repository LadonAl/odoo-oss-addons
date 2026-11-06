{
    'name': 'Payment Provider: Ziina',
    'summary': 'Card, Apple Pay and Google Pay payments through Ziina, the UAE business payment '
               'platform',
    'description': """
Payment Provider: Ziina
=======================
Customers pay on Ziina's hosted payment page (card, Apple Pay, Google Pay) and
come back to Odoo, which confirms the payment with Ziina's API. Refunds, full
and partial, are sent from Odoo. Test mode creates Ziina test payments with the
same API key.

Setup: Accounting > Configuration > Payment Providers > Ziina: paste the API key
from ziina.com/business/connect, press *Register Webhook*, choose Test Mode or
Enabled, publish. See README.md for the details.
""",
    'category': 'Accounting/Payment Providers',
    'version': '19.0.1.0.0',
    'author': 'LadonAl Labz',
    'website': 'https://github.com/LadonAl/odoo-oss-addons',
    'license': 'LGPL-3',
    'depends': ['payment'],
    'data': [
        'views/payment_ziina_templates.xml',
        'views/payment_provider_views.xml',
        'data/payment_provider_data.xml',
        'data/ir_cron_data.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
}
