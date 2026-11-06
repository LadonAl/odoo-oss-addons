import logging
import re
from datetime import date, timedelta

import requests
from lxml import html
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# The by-date endpoint behind centralbank.ae/en/forex-eibor/exchange-rates/.
# It answers with an HTML fragment: a "Last updated: <weekday> <date> <time>"
# line and a table of "<currency name> | <AED per one unit>" rows, empty on
# days without a fixing (weekends, holidays, today before ~18:00 Gulf time).
# The undated GetExchangeRateAllCurrency ignores any date and returns the
# latest fixing, so it cannot be used for back-filling.
URL = 'https://centralbank.ae/umbraco/Surface/Exchange/GetExchangeRateAllCurrencyDate'
LATEST_URL = 'https://centralbank.ae/umbraco/Surface/Exchange/GetExchangeRateAllCurrency'
USER_AGENT = 'Mozilla/5.0 (compatible; Odoo currency_rate_update_cbuae)'
TIMEOUT = 20
# A scheduled run normally finds days without a fixing (weekends, today before
# publication) and retries later without a word. The UAE never goes more than
# a week without one, though, so a longer empty stretch means the page stopped
# answering and gets reported.
MAX_QUIET_DAYS = 7

# The CBUAE names currencies but does not code them. Keys are the published
# labels lowercased and whitespace-collapsed, typos included ("Bahrani"), plus
# the correct spelling where they are misspelt in case they get fixed. A label
# missing here is skipped and logged rather than failing the whole update.
CURRENCY_CODES = {
    'us dollar': 'USD',
    'argentine peso': 'ARS',
    'australian dollar': 'AUD',
    'bangladesh taka': 'BDT',
    'bahrani dinar': 'BHD',
    'bahraini dinar': 'BHD',
    'brunei dollar': 'BND',
    'brazilian real': 'BRL',
    'botswana pula': 'BWP',
    'belarus rouble': 'BYN',
    'canadian dollar': 'CAD',
    'swiss franc': 'CHF',
    'chilean peso': 'CLP',
    'chinese yuan - offshore': 'CNH',
    'chinese yuan': 'CNY',
    'colombian peso': 'COP',
    'czech koruna': 'CZK',
    'danish krone': 'DKK',
    'algerian dinar': 'DZD',
    'egypt pound': 'EGP',
    'euro': 'EUR',
    'gb pound': 'GBP',
    'hongkong dollar': 'HKD',
    'hong kong dollar': 'HKD',
    'hungarian forint': 'HUF',
    'indonesia rupiah': 'IDR',
    'indian rupee': 'INR',
    'iceland krona': 'ISK',
    'jordan dinar': 'JOD',
    'japanese yen': 'JPY',
    'kenya shilling': 'KES',
    'korean won': 'KRW',
    'kuwaiti dinar': 'KWD',
    'kazakhstan tenge': 'KZT',
    'lebanon pound': 'LBP',
    'sri lanka rupee': 'LKR',
    'moroccan dirham': 'MAD',
    'macedonia denar': 'MKD',
    'mexican peso': 'MXN',
    'malaysia ringgit': 'MYR',
    'nigerian naira': 'NGN',
    'norwegian krone': 'NOK',
    'newzealand dollar': 'NZD',
    'new zealand dollar': 'NZD',
    'omani rial': 'OMR',
    'peru sol': 'PEN',
    'philippine piso': 'PHP',
    'philippine peso': 'PHP',
    'pakistan rupee': 'PKR',
    'polish zloty': 'PLN',
    'qatari riyal': 'QAR',
    'serbian dinar': 'RSD',
    'russia rouble': 'RUB',
    'saudi riyal': 'SAR',
    'sudanese pound': 'SDG',
    'swedish krona': 'SEK',
    'singapore dollar': 'SGD',
    'thai baht': 'THB',
    'tunisian dinar': 'TND',
    'turkish lira': 'TRY',
    'trin tob dollar': 'TTD',
    'trinidad and tobago dollar': 'TTD',
    'taiwan dollar': 'TWD',
    'tanzania shilling': 'TZS',
    'uganda shilling': 'UGX',
    'vietnam dong': 'VND',
    'yemen rial': 'YER',
    'south africa rand': 'ZAR',
    'zambian kwacha': 'ZMW',
    'azerbaijan manat': 'AZN',
    'bulgarian lev': 'BGN',
    'croatian kuna': 'HRK',
    'ethiopian birr': 'ETB',
    'iraqi dinar': 'IQD',
    'israeli new shekel': 'ILS',
    'libyan dinar': 'LYD',
    'mauritian rupee': 'MUR',
    'nepalese rupee': 'NPR',
    'romanian leu': 'RON',
    'syrian pound': 'SYP',
    'turkmen manat': 'TMT',
    'uzbekistani som': 'UZS',
    'iranian rial': 'IRR',
}

MONTHS = ('january', 'february', 'march', 'april', 'may', 'june', 'july',
          'august', 'september', 'october', 'november', 'december')
PUBLISHED_RE = re.compile(r'Last updated:\D*?(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})')


def make_session():
    """A session that retries the CBUAE's transient failures: its origin times
    out behind Cloudflare now and then (522), and one failed day would
    otherwise abort the whole range."""
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1, allowed_methods=['GET'],
                  status_forcelist=(500, 502, 503, 504, 520, 521, 522, 523, 524))
    session.mount('https://', HTTPAdapter(max_retries=retry))
    return session


def fetch(session, day=None):
    """The CBUAE rates fragment for `day`, or the latest one, as text."""
    url, params = (URL, {'dateTime': day.isoformat()}) if day else (LATEST_URL, None)
    response = session.get(url, params=params, headers={'User-Agent': USER_AGENT},
                           timeout=TIMEOUT)
    response.raise_for_status()
    return response.text


def parse(fragment):
    """(publication date or None, [(label, rate text), ...]) of a fragment.

    Raises ValueError when the answer is not the rates fragment at all, which
    is what a Cloudflare challenge or a redesigned page looks like.
    """
    tree = html.fromstring(fragment) if fragment.strip() else None
    tables = tree.xpath('//table[.//th[normalize-space()="Rates"]]') if tree is not None else []
    if not tables:
        raise ValueError('The Central Bank of the UAE answered without its rates table '
                         '(blocked by its firewall, or the page changed).')
    rows = []
    for tr in tables[0].xpath('.//tbody/tr'):
        cells = [td.text_content().strip() for td in tr.xpath('./td')]
        if len(cells) >= 2:
            rows.append((cells[-2], cells[-1]))
    published = None
    match = PUBLISHED_RE.search(tree.text_content())
    if match and match.group(2).lower() in MONTHS:
        published = date(int(match.group(3)), MONTHS.index(match.group(2).lower()) + 1,
                         int(match.group(1)))
    return published, rows


def aed_rates(fragment, unknown, day=None):
    """(publication date, {ISO code: AED per one unit, AED included}) of a
    fragment; (None, {}) when it holds no rates, or rates of another day than
    `day` when one is given.

    Labels without a known code are added to `unknown`.
    """
    published, rows = parse(fragment)
    if not rows:
        return None, {}
    if published is None:
        raise ValueError('The Central Bank of the UAE rates have no readable '
                         '"Last updated" date (the page changed).')
    if day and published != day:
        # The endpoint answered with another day's fixing instead of nothing.
        _logger.warning('CBUAE: asked for the rates of %s, got those of %s; skipped',
                        day, published)
        return None, {}
    rates = {'AED': 1.0}
    for label, value in rows:
        code = CURRENCY_CODES.get(' '.join(label.split()).lower())
        if not code:
            unknown.add(label)
            continue
        try:
            rate = float(value)
        except ValueError:
            rate = 0.0
        if rate > 0:
            rates[code] = rate
        else:
            _logger.warning('CBUAE: unusable rate %r for %s on %s', value, label, published)
    return published, rates


class ResCurrencyRateProviderCBUAE(models.Model):
    _inherit = 'res.currency.rate.provider'

    service = fields.Selection(
        selection_add=[('CBUAE', 'Central Bank of the UAE')],
        ondelete={'CBUAE': 'set default'},
    )

    def _get_supported_currencies(self):
        self.ensure_one()
        if self.service != 'CBUAE':
            return super()._get_supported_currencies()  # pragma: no cover
        return sorted(set(CURRENCY_CODES.values()) | {'AED'})

    def _obtain_rates(self, base_currency, currencies, date_from, date_to):
        self.ensure_one()
        if self.service != 'CBUAE':
            return super()._obtain_rates(
                base_currency, currencies, date_from, date_to
            )  # pragma: no cover
        if base_currency not in self._get_supported_currencies():
            raise UserError(self.env._(
                'The Central Bank of the UAE does not quote %(currency)s, the '
                'currency of %(company)s.',
                currency=base_currency, company=self.company_id.name,
            ))
        wanted = set(currencies) - {base_currency}
        unknown = set()
        content = {}

        def add(published, rates):
            base = rates.get(base_currency)
            if base:
                # AED per base unit / AED per foreign unit = foreign units per
                # base unit, the direction Odoo stores.
                content[published.isoformat()] = {
                    code: base / rates[code] for code in wanted if code in rates
                }
            elif rates:
                _logger.warning('CBUAE: no %s rate on %s', base_currency, published)

        # One request per day: the CBUAE has no range query. Days in the future
        # cannot have a fixing yet.
        today = date.today()
        day, last = date_from, min(date_to, today)
        scheduled = self.env.context.get('scheduled')
        with make_session() as session:
            while day <= last:
                add(*aed_rates(fetch(session, day), unknown, day))
                day += timedelta(days=1)
            if not content:
                _logger.info('CBUAE: no fixing from %s to %s', date_from, date_to)
            if not content and (not scheduled or (last - date_from).days >= MAX_QUIET_DAYS):
                latest, rates = self._cbuae_latest(session, unknown)
                if not scheduled and date_to >= today and latest:
                    # "Update now" before today's fixing is out: load the latest
                    # one, under its own date (Odoo applies it to today anyway).
                    add(latest, rates)
                if not content:
                    # currency_rate_update drops an empty result without a
                    # trace, so a manual update would look like it did nothing.
                    # Raising gets the reason posted on the provider's chatter.
                    raise UserError(self._cbuae_no_fixing_message(date_from, date_to, latest))
        if unknown:
            _logger.warning('CBUAE: no ISO code for %s; add it to CURRENCY_CODES',
                            ', '.join(sorted(unknown)))
        return content

    def _cbuae_latest(self, session, unknown):
        """The latest fixing, (None, {}) if it cannot be read."""
        try:
            return aed_rates(fetch(session), unknown)
        except (requests.RequestException, ValueError):
            _logger.warning('CBUAE: could not look up the latest fixing', exc_info=True)
            return None, {}

    def _cbuae_no_fixing_message(self, date_from, date_to, latest):
        message = self.env._(
            'The Central Bank of the UAE published no rates from %(date_from)s to '
            '%(date_to)s. It publishes on UAE banking days (Monday to Friday) around '
            '18:00 UAE time.',
            date_from=date_from, date_to=date_to,
        )
        if latest:
            message += ' ' + self.env._(
                'The latest are those of %(date)s: update from that date to load them.',
                date=latest,
            )
        return message
