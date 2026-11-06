ODOO_SYMBOLS = {'base.SAR': 'SR', 'base.AED': 'AED'}
SIGNS = {'base.SAR': '⃁', 'base.AED': '⃃'}


def post_init_hook(env):
    # The company report stylesheet is a stored attachment that Odoo rebuilds
    # only when a company's report settings change; rebuild it for our font.
    env['res.company']._update_asset_style()


def uninstall_hook(env):
    """Back to Odoo's symbols, which every font can draw, unless someone has
    changed them since."""
    for xmlid, symbol in ODOO_SYMBOLS.items():
        currency = env.ref(xmlid, raise_if_not_found=False)
        if currency and currency.symbol == SIGNS[xmlid]:
            currency.write({'symbol': symbol, 'position': 'after'})
