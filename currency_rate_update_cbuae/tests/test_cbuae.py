"""CBUAE provider against saved answers: tests/data holds the fragment the
CBUAE returned for 2026-10-20 (trimmed to ten rows) and for Saturday
2026-10-17 (no fixing)."""
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import requests

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..models import res_currency_rate_provider_cbuae as cbuae

DATA = Path(__file__).parent / 'data'
FIXING_DAY = date(2026, 10, 20)
FIXING = (DATA / 'cbuae_2026-10-20.html').read_text(encoding='utf-8')
NO_FIXING = (DATA / 'cbuae_2026-10-17.html').read_text(encoding='utf-8')
CHALLENGE = ('<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title>'
             '</head><body><noscript>Enable JavaScript and cookies to continue</noscript>'
             '</body></html>')

# AED per one unit on 2026-10-20, as published.
AED_PER = {'USD': 3.6725, 'EUR': 4.125941, 'GBP': 4.917662, 'SAR': 0.979072,
           'QAR': 1.007545, 'OMR': 9.538713, 'BHD': 9.736214, 'KWD': 11.923701}
GCC = {'AED', 'SAR', 'QAR', 'OMR', 'BHD', 'KWD'}


def answers(by_day, latest=FIXING):
    """A stand-in for cbuae.fetch serving `by_day`, no fixing on other days and
    `latest` (a fragment, or an exception to raise) for the undated request."""
    calls = []

    def fake_fetch(session, day=None):
        calls.append(day)
        if day is None:
            if isinstance(latest, Exception):
                raise latest
            return latest
        return by_day.get(day, NO_FIXING)
    return fake_fetch, calls


@tagged('post_install', '-at_install')
class TestCBUAE(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['res.currency'].with_context(active_test=False).search(
            [('name', 'in', [*GCC, 'USD', 'EUR', 'GBP'])]).active = True
        cls.aed_company = cls.env['res.company'].create(
            {'name': 'CBUAE AED company', 'currency_id': cls.env.ref('base.AED').id})
        cls.eur_company = cls.env['res.company'].create(
            {'name': 'CBUAE EUR company', 'currency_id': cls.env.ref('base.EUR').id})
        Provider = cls.env['res.currency.rate.provider']
        cls.aed_provider = Provider.create({
            'company_id': cls.aed_company.id,
            'service': 'CBUAE',
            'currency_ids': [(6, 0, cls._currencies('USD', 'EUR', 'SAR', 'KWD').ids)],
        })
        cls.eur_provider = Provider.create({
            'company_id': cls.eur_company.id,
            'service': 'CBUAE',
            'currency_ids': [(6, 0, cls._currencies('AED', 'SAR', 'USD').ids)],
        })

    @classmethod
    def _currencies(cls, *codes):
        return cls.env['res.currency'].search([('name', 'in', codes)])

    def _obtain(self, provider, base, currencies, date_from=FIXING_DAY, date_to=FIXING_DAY,
                by_day=None, **answer_kw):
        fake_fetch, calls = answers({FIXING_DAY: FIXING} if by_day is None else by_day,
                                    **answer_kw)
        with patch.object(cbuae, 'fetch', fake_fetch):
            return provider._obtain_rates(base, currencies, date_from, date_to), calls

    def test_supported_currencies(self):
        supported = self.aed_provider._get_supported_currencies()
        self.assertLessEqual(GCC | {'USD', 'EUR', 'GBP'}, set(supported))
        self.assertTrue(all(len(code) == 3 and code.isupper() for code in supported))
        self.assertIn(self.env.ref('base.SAR'), self.aed_provider.available_currency_ids)

    def test_session_retries_transient_errors(self):
        with cbuae.make_session() as session:
            retry = session.get_adapter(cbuae.URL).max_retries
        self.assertGreaterEqual(retry.total, 2)
        self.assertIn(522, retry.status_forcelist)

    def test_parse(self):
        published, rows = cbuae.parse(FIXING)
        self.assertEqual(published, FIXING_DAY)
        self.assertEqual(len(rows), 10)
        self.assertIn(('Bahrani Dinar', '9.736214'), rows)
        self.assertEqual(cbuae.parse(NO_FIXING), (None, []))

    def test_aed_company(self):
        """An AED company stores foreign units per dirham: 1 / published."""
        content, _calls = self._obtain(self.aed_provider, 'AED', ['USD', 'EUR', 'SAR', 'KWD', 'AED'])
        self.assertEqual(list(content), ['2026-10-20'])
        rates = content['2026-10-20']
        self.assertEqual(set(rates), {'USD', 'EUR', 'SAR', 'KWD'})
        for code, rate in rates.items():
            self.assertAlmostEqual(rate, 1 / AED_PER[code], places=12)

    def test_eur_company_crosses_through_aed(self):
        content, _calls = self._obtain(self.eur_provider, 'EUR', ['AED', 'SAR', 'USD', 'EUR'])
        rates = content['2026-10-20']
        self.assertAlmostEqual(rates['AED'], 4.125941, places=12)
        self.assertAlmostEqual(rates['SAR'], 4.125941 / 0.979072, places=12)
        self.assertAlmostEqual(rates['USD'], 4.125941 / 3.6725, places=12)
        self.assertNotIn('EUR', rates)

    def test_days_without_fixing_are_skipped(self):
        content, calls = self._obtain(self.aed_provider, 'AED', ['USD'],
                                      date_from=date(2026, 10, 17), date_to=date(2026, 10, 21))
        self.assertEqual(list(content), ['2026-10-20'])
        self.assertEqual(calls, [date(2026, 10, d) for d in range(17, 22)])

    def test_future_days_are_not_requested(self):
        today = date.today()
        cron = self.aed_provider.with_context(scheduled=True)
        _content, calls = self._obtain(cron, 'AED', ['USD'], by_day={today: NO_FIXING},
                                       date_from=today, date_to=today + timedelta(days=5))
        self.assertEqual(calls, [today])

    def test_fixing_of_another_day_is_ignored(self):
        """If the endpoint ever falls back to the latest fixing, do not stamp
        it with the requested date."""
        other_day = date(2026, 10, 19)
        cron = self.aed_provider.with_context(scheduled=True)
        content, _calls = self._obtain(cron, 'AED', ['USD'], date_from=other_day,
                                       date_to=other_day, by_day={other_day: FIXING})
        self.assertEqual(content, {})

    def test_update_now_before_todays_fixing_loads_the_latest(self):
        """The wizard's default range is today, which has no fixing before
        ~18:00 UAE time: load the latest one, under its own date."""
        today = date.today()
        content, calls = self._obtain(self.aed_provider, 'AED', ['USD', 'SAR'], by_day={},
                                      date_from=today, date_to=today)
        self.assertEqual(calls, [today, None])
        self.assertEqual(list(content), ['2026-10-20'])
        self.assertAlmostEqual(content['2026-10-20']['SAR'], 1 / 0.979072, places=12)

    def test_update_now_writes_the_latest_rates(self):
        today = date.today()
        fake_fetch, _calls = answers({})
        with patch.object(cbuae, 'fetch', fake_fetch):
            self.aed_provider._update(today, today)
        rates = self.env['res.currency.rate'].search([('provider_id', '=', self.aed_provider.id)])
        self.assertEqual(set(rates.mapped('name')), {FIXING_DAY})
        self.assertEqual(set(rates.currency_id.mapped('name')), {'USD', 'EUR', 'SAR', 'KWD'})

    def test_manual_run_without_fixing_says_so(self):
        """A past range without any fixing (a weekend): say so, and point to
        the latest one."""
        saturday = date(2026, 10, 17)
        with self.assertRaisesRegex(UserError, 'published no rates.*2026-10-20') as raised:
            self._obtain(self.aed_provider, 'AED', ['USD'], date_from=saturday, date_to=saturday)
        self.assertIn('2026-10-17', str(raised.exception))

    def test_manual_run_without_fixing_when_latest_lookup_fails(self):
        with self.assertRaisesRegex(UserError, 'published no rates') as raised, \
                self.assertLogs(cbuae.__name__, 'WARNING'):
            self._obtain(self.aed_provider, 'AED', ['USD'], date_from=date(2026, 10, 17),
                         date_to=date(2026, 10, 17),
                         latest=requests.ConnectionError('unreachable'))
        self.assertNotIn('latest', str(raised.exception))

    def test_manual_update_without_fixing_is_posted(self):
        saturday = date(2026, 10, 17)
        fake_fetch, _calls = answers({})
        with patch.object(cbuae, 'fetch', fake_fetch):
            self.aed_provider._update(saturday, saturday)
        body = str(self.aed_provider.message_ids[0].body)
        self.assertIn('published no rates', body)
        self.assertIn('2026-10-20', body)

    def test_scheduled_run_waits_quietly_for_a_fixing(self):
        cron = self.aed_provider.with_context(scheduled=True)
        content, calls = self._obtain(cron, 'AED', ['USD'], date_from=date(2026, 10, 17),
                                      date_to=date(2026, 10, 18))
        self.assertEqual(content, {})
        self.assertNotIn(None, calls)

    def test_scheduled_run_reports_a_week_without_fixing(self):
        cron = self.aed_provider.with_context(scheduled=True)
        with self.assertRaisesRegex(UserError, 'published no rates'):
            self._obtain(cron, 'AED', ['USD'], by_day={}, date_from=date(2026, 10, 12),
                         date_to=date(2026, 10, 19))

    def test_unknown_label_is_skipped(self):
        renamed = FIXING.replace('>Saudi Riyal<', '>Saudi Arabian Riyal<')
        with self.assertLogs(cbuae.__name__, 'WARNING') as logs:
            content, _calls = self._obtain(self.aed_provider, 'AED', ['USD', 'SAR'],
                                           by_day={FIXING_DAY: renamed})
        self.assertEqual(set(content['2026-10-20']), {'USD'})
        self.assertIn('Saudi Arabian Riyal', logs.output[0])

    def test_blocked_answer_raises(self):
        with self.assertRaises(ValueError):
            self._obtain(self.aed_provider, 'AED', ['USD'], by_day={FIXING_DAY: CHALLENGE})

    def test_unquoted_company_currency(self):
        with self.assertRaises(UserError):
            self._obtain(self.aed_provider, 'XAF', ['USD'])

    def test_update_writes_rates(self):
        fake_fetch, _calls = answers({FIXING_DAY: FIXING})
        with patch.object(cbuae, 'fetch', fake_fetch):
            self.aed_provider._update(FIXING_DAY, FIXING_DAY)
        rate = self.env['res.currency.rate'].search([
            ('company_id', '=', self.aed_company.id),
            ('currency_id', '=', self.env.ref('base.SAR').id),
            ('name', '=', FIXING_DAY),
        ])
        self.assertEqual(len(rate), 1)
        self.assertAlmostEqual(rate.rate, 1 / 0.979072, places=6)
        self.assertEqual(rate.provider_id, self.aed_provider)

    def test_blocked_update_is_posted_not_raised(self):
        fake_fetch, _calls = answers({FIXING_DAY: CHALLENGE})
        with patch.object(cbuae, 'fetch', fake_fetch):
            self.aed_provider._update(FIXING_DAY, FIXING_DAY)
        self.assertIn('rates table', self.aed_provider.message_ids[0].body)
