import base64

from odoo.tests import TransactionCase, tagged

SCSS = 'currency_symbol_sar_aed/static/src/scss/'


@tagged('post_install', '-at_install')
class TestSigns(TransactionCase):
    def test_amounts_lead_with_the_sign(self):
        self.assertEqual(self.env.ref('base.SAR').format(1234.5), '⃁\N{NO-BREAK SPACE}1,234.50')
        self.assertEqual(self.env.ref('base.AED').format(1234.5), '⃃\N{NO-BREAK SPACE}1,234.50')

    def _files(self, bundle):
        return [f['url'].lstrip('/') for f in self.env['ir.qweb']._get_asset_bundle(bundle).files]

    def test_browser_bundles_lead_with_the_signs_font(self):
        for bundle in ('web.assets_backend', 'web.assets_frontend'):
            files = self._files(bundle)
            # Right after Odoo's helpers, before any font stack is built.
            utils = files.index('web/static/src/scss/utils.scss')
            self.assertEqual(files[utils + 1], SCSS + 'font_stack.scss', bundle)
            self.assertIn(SCSS + 'sar_aed_signs.scss', files, bundle)

    def test_report_bundle_falls_back_to_the_signs_font(self):
        files = self._files('web.report_assets_common')
        self.assertNotIn(SCSS + 'font_stack.scss', files)
        self.assertIn(SCSS + 'sar_aed_signs.scss', files)
        self.assertIn(SCSS + 'report.scss', files)

    def test_report_company_font_falls_back_to_the_signs(self):
        css = base64.b64decode(self.env.ref('web.asset_styles_company_report').datas).decode()
        company = self.env.company
        self.assertIn(f"font-family: {company.font or 'Lato'}, 'SAR AED Signs';", css)
