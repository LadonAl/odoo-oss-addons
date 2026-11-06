{
    'name': 'Currency Rate Update: Central Bank of the UAE',
    'summary': 'GCC exchange rates (AED, SAR, QAR, OMR, BHD, KWD and ~70 more) from the CBUAE',
    'description': """
Currency Rate Update: Central Bank of the UAE
=============================================
Adds a *Central Bank of the UAE* provider to OCA ``currency_rate_update``.

The CBUAE publishes, every UAE banking day around 18:00 Gulf time, the rates of
the UAE Dirham against about 75 currencies, including the other GCC currencies
(Saudi Riyal, Qatari Riyal, Omani Rial, Bahraini Dinar, Kuwaiti Dinar). These
are the rates the UAE uses for VAT obligations.

The provider works for any company currency the CBUAE quotes, not only AED:
for a EUR or GBP company the rates are crossed through the Dirham, so it can
supply the GCC currencies ECB does not publish.

Setup: Accounting > Configuration > Accounting > Currency Rates Providers, pick
*Central Bank of the UAE* and the currencies to update.
""",
    'category': 'Financial Management/Configuration',
    'version': '19.0.1.0.3',
    'author': 'LadonAl Labz',
    'website': 'https://github.com/LadonAl/odoo-oss-addons',
    'license': 'AGPL-3',
    'depends': ['currency_rate_update'],
    'installable': True,
}
