# Currency Rate Update: Central Bank of the UAE

Adds a **Central Bank of the UAE** provider to OCA's
[`currency_rate_update`](https://github.com/OCA/currency/tree/19.0/currency_rate_update),
so Odoo loads the CBUAE's daily exchange rates on its own.

The CBUAE publishes the rate of the UAE dirham against about 75 currencies
every UAE banking day, around 18:00 UAE time. These are the rates the UAE uses
for VAT, and they cover the Gulf currencies that the European Central Bank
does not publish: Saudi riyal, Qatari riyal, Omani rial, Bahraini dinar and
Kuwaiti dinar.

The company currency does not have to be AED. For any company currency the
CBUAE quotes (EUR, GBP, USD...), the rates are crossed through the dirham, so
a European company can take its SAR or QAR rates from here and the rest from
ECB.

## Requirements

* Odoo 19.0.
* `currency_rate_update` from [OCA/currency](https://github.com/OCA/currency/tree/19.0)
  on the addons path.
* Outbound HTTPS from the Odoo server to `centralbank.ae`.

## Setup

1. Install **Currency Rate Update: Central Bank of the UAE** (Apps). It pulls in
   `currency_rate_update`.
2. Activate the currencies you need (Invoicing → Configuration → Accounting →
   Currencies).
3. Open **Invoicing → Configuration → Accounting → Currency Rates Providers**,
   create a provider, set **Provider** to *Central Bank of the UAE*, pick the
   company (multi-company databases only) and the currencies to update, and
   save. Creating a provider needs Settings (administrator) access.
4. Press **Update Rates Now**, then **Update** in the dialog (start and end
   date default to today), to load the latest rates straight away. After that,
   OCA's scheduled action keeps them current, daily by default (**Scheduled
   Update Interval**). Scheduled updates run only while *Automatic Currency
   Rates (OCA)* is on in the accounting settings, which it is by default.

To fill in past rates, press **Update Rates Now** and pick an earlier
**Start Date**: the CBUAE keeps its history, and the provider asks for each
day of the range.

## How it works

The CBUAE has no API. The provider reads the HTML fragment behind its
[exchange rates page](https://www.centralbank.ae/en/forex-eibor/exchange-rates/),
one request per day of the range, and turns it into Odoo rates:

* **Currency names, not codes.** The page names each currency ("Saudi Riyal",
  "Bahrani Dinar", typos included) and gives no ISO code. `CURRENCY_CODES` in
  `models/res_currency_rate_provider_cbuae.py` maps the names to codes. A name
  it does not know is skipped and logged (`CBUAE: no ISO code for ...`), and
  the other rates still load. Add the name to the map to pick it up.
* **Direction.** The CBUAE quotes dirhams per unit of each currency. Odoo
  stores units of each currency per unit of the company currency, so the
  provider divides through the dirham.
* **Days without rates.** Weekends, UAE holidays and today before about 18:00
  have no rates. Those days are skipped. A day that comes back with another
  day's rates is skipped too, so a rate is never stored under the wrong date.
* **Update Rates Now before today's rates are out.** Odoo then gets the latest
  published rates, stored under their own date. Odoo uses the most recent rate
  for today anyway.
* **Nothing published in the range.** A manual update says so on the
  provider's chatter, with the date of the latest published rates. The
  scheduled update waits quietly and tries again the next day. It only reports
  on the chatter after a week without any rates, which means the page stopped
  answering or changed, and repeats that daily until rates come back.
* **Transient errors.** The CBUAE site sits behind Cloudflare and sometimes
  times out (HTTP 500, 502-504 and Cloudflare's 520-524). Each request is
  retried three times with a backoff. A firewall challenge, or a page without
  the rates table or its "Last updated" date, is reported on the provider's
  chatter instead of storing wrong rates.

## Limits

* The CBUAE can change its page at any time. The tests pin the format the
  provider understands. Most changes show up as a chatter message on the
  provider; a change that only empties the table looks like days without
  rates and is reported after a week.
* Only currencies the CBUAE quotes can be updated; **Currencies** on the
  provider offers just those. A company whose own currency the CBUAE does not
  quote cannot use this provider.

## Tests

The tests replace the CBUAE with two recorded answers (a banking day and a
Saturday), so they run without network access:

```bash
odoo -d test_db -i currency_rate_update_cbuae --test-enable \
  --test-tags /currency_rate_update_cbuae --stop-after-init
```

## License and credits

AGPL-3.0, like the OCA addon it extends. Full text in
[`LICENSES/AGPL-3.0.txt`](../LICENSES/AGPL-3.0.txt).

Made by [LadonAl Labz](https://github.com/LadonAl). Not affiliated with the
Central Bank of the UAE. The rates are the CBUAE's published figures; check
their terms of use for your purpose.
