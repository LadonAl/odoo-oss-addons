# Odoo open-source addons by LadonAl Labz

Free, open-source addons for [Odoo](https://www.odoo.com) 19.0, made for
businesses that work in the UAE and the Gulf. They are built and tested on
Odoo 19.0 Community.

| Addon | What it does | License |
|---|---|---|
| [`payment_ziina`](payment_ziina/README.md) | Payment provider for [Ziina](https://ziina.com), the UAE business payment platform: customers pay on Ziina's page by card, Apple Pay or Google Pay, Odoo confirms each payment with Ziina and books it, refunds go out from Odoo. | LGPL-3 |
| [`currency_rate_update_cbuae`](currency_rate_update_cbuae/README.md) | Daily exchange rates from the Central Bank of the UAE for OCA's `currency_rate_update`: the dirham against about 75 currencies, all GCC ones included (SAR, QAR, OMR, BHD, KWD). | AGPL-3 |
| [`currency_symbol_sar_aed`](currency_symbol_sar_aed/README.md) | The official Saudi riyal (U+20C1) and UAE dirham (U+20C3) signs as currency symbols, with a small bundled font so Odoo's backend, website, portal and PDF reports can draw them. | LGPL-3 |

Each addon's README covers setup, how it works and its limits.

## Branches

One branch per Odoo version, as in the [OCA](https://github.com/OCA) repositories:
`19.0` holds the addons for Odoo 19.0.

## Install

The addons sit at the root of the repository, so the checkout itself is an
entry for Odoo's `addons_path`.

1. Get the code, either as a plain clone:

   ```bash
   git clone -b 19.0 https://github.com/LadonAl/odoo-oss-addons.git
   ```

   or as a git submodule of your own deployment repository:

   ```bash
   git submodule add -b 19.0 https://github.com/LadonAl/odoo-oss-addons.git odoo-oss-addons
   ```

   You can also copy a single addon folder into an existing addons directory.

2. Add the folder to `addons_path` in the Odoo configuration file (or the
   `--addons-path` option) and restart Odoo.
3. In Odoo, turn on developer mode, open **Apps → Update Apps List**, then
   search for the addon and install it.

`currency_rate_update_cbuae` also needs `currency_rate_update` from
[OCA/currency](https://github.com/OCA/currency/tree/19.0) on the addons path.
The other two need nothing outside Odoo.

## Tests

Every addon has tests that run without network access (the outside services
are replaced by recorded or canned answers):

```bash
odoo -d test_db -i payment_ziina,currency_rate_update_cbuae,currency_symbol_sar_aed \
  --test-enable --test-tags /payment_ziina,/currency_rate_update_cbuae,/currency_symbol_sar_aed \
  --stop-after-init
```

Use a throwaway database: the tests install the addons into it.

## Issues and contributions

Bug reports and pull requests are welcome on
[GitHub](https://github.com/LadonAl/odoo-oss-addons/issues). Please say which
Odoo version and edition you run, and include the server log for errors.

## License

Each addon carries its own license, named in its `__manifest__.py`: AGPL-3 for
`currency_rate_update_cbuae` (it extends an AGPL-3 OCA addon), LGPL-3 for the
other two. The full texts are in [`LICENSES/`](LICENSES). The font bundled
with `currency_symbol_sar_aed` combines the Saudi Riyal Font (SIL Open Font
License 1.1, with its author's attribution terms) and the MIT-licensed dirham
sign: credits are in that addon's README, the license texts in its
`static/fonts/LICENSE.txt`.

Odoo is a trademark of Odoo S.A. Ziina is a trademark of its owner. These
addons are not made or endorsed by Odoo S.A., Ziina or the Central Bank of the
UAE.
