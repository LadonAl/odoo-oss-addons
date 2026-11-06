{
    'name': 'SAR and AED Currency Signs',
    'summary': 'The official Saudi riyal (U+20C1) and UAE dirham (U+20C3) signs, '
               'with a bundled font for devices that cannot draw them yet',
    'description': """
SAR and AED Currency Signs
==========================
Sets the currency symbols to the signs Unicode now encodes, placed before the
amount as both central banks prescribe:

* Saudi riyal: U+20C1 SAUDI RIYAL SIGN (Unicode 17.0, 2025)
* UAE dirham: U+20C3 UAE DIRHAM SIGN (Unicode 18.0, 2026)

Few fonts draw them yet, so the module ships a small font holding only these
two signs and has the backend, the website, the portal and the reports (HTML
and PDF) draw them with it. Should it fail to load, the device's own fonts
take over (Windows, for one, already has the riyal sign). Emails and exports
carry the plain character and depend on the reader's fonts.

Uninstalling restores Odoo's default symbols (SR, AED, after the amount).
""",
    'category': 'Accounting/Localizations',
    'version': '19.0.1.0.0',
    'author': 'LadonAl Labz',
    'website': 'https://github.com/LadonAl/odoo-oss-addons',
    'license': 'LGPL-3',
    'depends': ['web'],
    'data': [
        'data/res_currency_data.xml',
        'views/report_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            ('after', 'web/static/src/scss/utils.scss', 'currency_symbol_sar_aed/static/src/scss/font_stack.scss'),
            'currency_symbol_sar_aed/static/src/scss/sar_aed_signs.scss',
        ],
        'web.assets_frontend': [
            ('after', 'web/static/src/scss/utils.scss', 'currency_symbol_sar_aed/static/src/scss/font_stack.scss'),
            'currency_symbol_sar_aed/static/src/scss/sar_aed_signs.scss',
        ],
        'web.report_assets_common': [
            'currency_symbol_sar_aed/static/src/scss/sar_aed_signs.scss',
            'currency_symbol_sar_aed/static/src/scss/report.scss',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
}
