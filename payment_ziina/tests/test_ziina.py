import hashlib
import hmac
import json
import time
import uuid
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import requests

from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

from odoo.addons.payment.tests.http_common import PaymentHttpCommon
from odoo.addons.payment_ziina import const
from odoo.addons.payment_ziina.tests.common import ZiinaCommon

SEND = 'odoo.addons.payment.models.payment_provider.PaymentProvider._send_api_request'
REQUEST = 'odoo.addons.payment.models.payment_provider.requests.request'
TRIGGER = 'odoo.addons.base.models.ir_cron.IrCron._trigger'
CONTROLLER_LOGGER = 'odoo.addons.payment_ziina.controllers.main'
PROVIDER_LOGGER = 'odoo.addons.payment.models.payment_provider'
TX_LOGGER = 'odoo.addons.payment_ziina.models.payment_transaction'


@tagged('post_install', '-at_install')
class TestZiina(ZiinaCommon, PaymentHttpCommon):

    # === Helpers === #

    def _return(self, tx, outcome, token_outcome=None):
        params = {
            'reference': tx.reference,
            'outcome': outcome,
            'access_token': self._generate_test_access_token(tx.reference, token_outcome or outcome),
        }
        return self._make_http_get_request(self._build_url(const.RETURN_ROUTE), params=params)

    def _webhook(self, event, data, secret='dummy-webhook-secret', signature=None):
        body = json.dumps({'event': event, 'data': data}).encode()
        headers = {'Content-Type': 'application/json'}
        if signature is None and secret:
            signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if signature:
            headers['X-Hmac-Signature'] = signature
        return self.url_open(
            self._build_url(const.WEBHOOK_ROUTE), data=body, headers=headers, method='POST'
        )

    def _response(self, status, body):
        response = requests.Response()
        response.status_code = status
        response.reason = 'OK' if status < 400 else 'Bad Request'
        response.url = 'https://api-v2.ziina.com/api/'
        response._content = json.dumps(body).encode()
        return response

    def _post_process_cron(self):
        return self.env.ref('payment.cron_post_process_payment_tx')

    def _refund_data(self, **values):
        return dict({
            'id': '9d3a6c1e-2b4f-4e8a-9c7d-1f2e3d4c5b6a',
            'payment_intent_id': self.intent_id,
            'amount': 50000,
            'currency_code': 'AED',
            'status': 'pending',
            'created_at': '1712345679901',
        }, **values)

    # === Payment intent === #

    def test_payment_intent_payload(self):
        tx = self._create_transaction('redirect')
        payload = tx._ziina_prepare_payment_intent_payload()

        expires_in = int(payload['expiry']) / 1000 - time.time()
        self.assertAlmostEqual(expires_in, const.INTENT_LIFETIME_MINUTES * 60, delta=60)
        self.assertEqual(payload['amount'], 111111)
        self.assertEqual(payload['currency_code'], 'AED')
        self.assertEqual(payload['message'], tx.reference)
        self.assertIs(payload['test'], True)
        for outcome in const.RETURN_OUTCOMES:
            url = urlsplit(payload[f'{outcome}_url'])
            query = {key: values[0] for key, values in parse_qs(url.query).items()}
            self.assertEqual(url.path, const.RETURN_ROUTE)
            self.assertEqual(query, {
                'reference': tx.reference,
                'outcome': outcome,
                'access_token': self._generate_test_access_token(tx.reference, outcome),
            })

    def test_live_payment_intent_is_not_a_test(self):
        self.provider.state = 'enabled'
        tx = self._create_transaction('redirect')
        self.assertIs(tx._ziina_prepare_payment_intent_payload()['test'], False)

    def test_three_decimal_amounts_in_minor_units(self):
        kwd = self._enable_currency('KWD')
        tx = self._create_transaction('redirect', currency_id=kwd.id, amount=12.34)
        self.assertEqual(tx._ziina_prepare_payment_intent_payload()['amount'], 12340)

    def test_redirect_form_opens_ziina_page(self):
        tx = self._create_transaction('redirect')
        with patch(SEND, return_value=self.intent) as send:
            processing_values = tx._get_processing_values()

        self.assertEqual(send.call_args.args, ('POST', '/payment_intent'))
        self.assertEqual(tx.provider_reference, self.intent_id)
        form = self._extract_values_from_html_form(processing_values['redirect_form_html'])
        self.assertEqual(form['action'], f'https://pay.ziina.com/payment_intent/{self.intent_id}')
        self.assertEqual(form['method'], 'get')
        self.assertEqual(form['inputs'], {'lang': 'en'})

    def test_refused_payment_intent_sets_error(self):
        tx = self._create_transaction('redirect')
        error = ValidationError("The payment provider rejected the request.\nAmount too small")
        with patch(SEND, side_effect=error):
            tx._get_processing_values()
        self.assertEqual(tx.state, 'error')
        self.assertIn("Amount too small", tx.state_message)

    # === Return from Ziina's page === #

    def test_return_confirms_paid_intent(self):
        tx = self._create_ziina_transaction()
        with patch(SEND, return_value=self._intent()) as send:
            response = self._return(tx, 'success')

        self.assertEqual(send.call_args.args, ('GET', f'/payment_intent/{self.intent_id}'))
        self.assertEqual(tx.state, 'done')
        self.assertTrue(response.url.endswith('/payment/status'))

    def test_success_return_waits_for_unsettled_intent(self):
        tx = self._create_ziina_transaction()
        with patch(SEND, return_value=self._intent(status='requires_payment_instrument')):
            self._return(tx, 'success')
        self.assertEqual(tx.state, 'pending')

    def test_cancel_return_cancels_unpaid_intent(self):
        tx = self._create_ziina_transaction()
        with patch(SEND, return_value=self._intent(status='requires_payment_instrument')):
            self._return(tx, 'cancel')
        self.assertEqual(tx.state, 'cancel')

    def test_failure_return_reports_ziina_error(self):
        tx = self._create_ziina_transaction()
        intent = self._intent(status='failed', latest_error={'message': "Card declined", 'code': '402'})
        with patch(SEND, return_value=intent):
            self._return(tx, 'failure')
        self.assertEqual(tx.state, 'error')
        self.assertIn("Card declined", tx.state_message)

    def test_failure_return_ends_unstarted_payment(self):
        tx = self._create_ziina_transaction()
        with patch(SEND, return_value=self._intent(status='requires_payment_instrument')):
            self._return(tx, 'failure')
        self.assertEqual(tx.state, 'error')

    @mute_logger(CONTROLLER_LOGGER)
    def test_return_with_wrong_token_changes_nothing(self):
        tx = self._create_ziina_transaction()
        with patch(SEND) as send:
            response = self._return(tx, 'cancel', token_outcome='success')
        send.assert_not_called()
        self.assertEqual(tx.state, 'draft')
        self.assertTrue(response.url.endswith('/payment/status'))

    @mute_logger(CONTROLLER_LOGGER, 'odoo.addons.payment.models.payment_transaction')
    def test_return_ignores_what_it_cannot_check(self):
        unsent_tx = self._create_transaction('redirect', reference='unsent')
        tx = self._create_ziina_transaction()
        url = self._build_url(const.RETURN_ROUTE)
        with patch(SEND) as send:
            unknown = self._make_http_get_request(url, params={
                'reference': 'nope', 'outcome': 'success',
                'access_token': self._generate_test_access_token('nope', 'success'),
            })
            self._return(unsent_tx, 'cancel')  # No payment intent yet.
            self._make_http_get_request(url, params={
                'reference': tx.reference, 'outcome': 'refund',
                'access_token': self._generate_test_access_token(tx.reference, 'refund'),
            })
        send.assert_not_called()
        self.assertTrue(unknown.url.endswith('/payment/status'))
        self.assertEqual((unsent_tx.state, tx.state), ('draft', 'draft'))

    @mute_logger(CONTROLLER_LOGGER)
    def test_return_survives_ziina_outage(self):
        tx = self._create_ziina_transaction()
        with patch(SEND, side_effect=ValidationError("Could not establish the connection.")):
            response = self._return(tx, 'success')
        self.assertEqual(tx.state, 'draft')
        self.assertTrue(response.url.endswith('/payment/status'))

    # === Processing === #

    def test_payment_after_cancel_is_confirmed(self):
        tx = self._create_ziina_transaction(state='cancel')
        tx._process('ziina', self._intent())
        self.assertEqual(tx.state, 'done')

    def test_canceled_intent_cancels(self):
        tx = self._create_ziina_transaction()
        tx._process('ziina', self._intent(status='canceled'))
        self.assertEqual(tx.state, 'cancel')

    def test_amount_mismatch_sets_error(self):
        tx = self._create_ziina_transaction()
        tx._process('ziina', self._intent(amount=100))
        self.assertEqual(tx.state, 'error')

    def test_currency_mismatch_sets_error(self):
        tx = self._create_ziina_transaction()
        tx._process('ziina', self._intent(currency_code='USD'))
        self.assertEqual(tx.state, 'error')

    def test_card_brand_sets_payment_method(self):
        self.env.ref('payment.payment_method_mastercard').active = True
        tx = self._create_ziina_transaction()
        tx._process('ziina', self._intent())
        self.assertEqual(tx.payment_method_id.code, 'mastercard')

    def test_three_d_secure_is_pending(self):
        tx = self._create_ziina_transaction()
        tx._process('ziina', self._intent(status='requires_user_action'))
        self.assertEqual(tx.state, 'pending')

    @mute_logger(TX_LOGGER)
    def test_unknown_status_sets_error(self):
        tx = self._create_ziina_transaction()
        tx._process('ziina', self._intent(status='on_hold'))
        self.assertEqual(tx.state, 'error')
        self.assertIn('on_hold', tx.state_message)

    def test_test_payment_after_go_live_is_refused(self):
        tx = self._create_ziina_transaction()  # Created in Test Mode.
        self.provider.state = 'enabled'
        tx._process('ziina', self._intent())
        self.assertEqual(tx.state, 'error')
        self.assertFalse(tx.is_live)

    def test_live_payment_still_settles_in_test_mode(self):
        self.provider.state = 'enabled'
        tx = self._create_ziina_transaction()
        self.provider.state = 'test'
        tx._process('ziina', self._intent())
        self.assertEqual(tx.state, 'done')

    # === Webhook === #

    def test_webhook_takes_status_from_ziina_not_from_body(self):
        tx = self._create_ziina_transaction()
        with patch(SEND, return_value=self._intent(status='pending')) as send:
            response = self._webhook('payment_intent.status.updated', self._intent())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(send.call_args.args, ('GET', f'/payment_intent/{self.intent_id}'))
        self.assertEqual(tx.state, 'pending')

    def test_webhook_confirms_payment(self):
        tx = self._create_ziina_transaction()
        with patch(SEND, return_value=self._intent()):
            self._webhook('payment_intent.status.updated', self._intent())
        self.assertEqual(tx.state, 'done')

    @mute_logger(CONTROLLER_LOGGER)
    def test_webhook_rejects_wrong_signature(self):
        tx = self._create_ziina_transaction()
        with patch(SEND) as send:
            response = self._webhook(
                'payment_intent.status.updated', self._intent(), signature='0' * 64
            )
        self.assertEqual(response.status_code, 403)
        send.assert_not_called()
        self.assertEqual(tx.state, 'draft')

    @mute_logger(CONTROLLER_LOGGER)
    def test_webhook_rejects_missing_signature(self):
        self._create_ziina_transaction()
        with patch(SEND) as send:
            response = self._webhook('payment_intent.status.updated', self._intent(), secret=None)
        self.assertEqual(response.status_code, 403)
        send.assert_not_called()

    def test_webhook_without_secret_relies_on_ziina_data(self):
        self.provider.ziina_webhook_secret = False
        tx = self._create_ziina_transaction()
        with patch(SEND, return_value=self._intent()):
            response = self._webhook('payment_intent.status.updated', self._intent(), secret=None)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(tx.state, 'done')

    @mute_logger('odoo.addons.payment_ziina.models.payment_transaction')
    def test_webhook_acknowledges_unknown_intent(self):
        with patch(SEND) as send:
            response = self._webhook('payment_intent.status.updated', self._intent())
        self.assertEqual(response.status_code, 200)
        send.assert_not_called()

    @mute_logger(CONTROLLER_LOGGER)
    def test_webhook_acknowledges_other_events_and_garbage(self):
        self._create_ziina_transaction()
        url = self._build_url(const.WEBHOOK_ROUTE)
        with patch(SEND) as send:
            responses = [
                self._webhook('transfer.status.updated', {'id': self.intent_id}),
                self.url_open(url, data=b'not json', method='POST'),
                self.url_open(url, data=b'[1, 2]', method='POST'),
                self.url_open(url, json={'event': [], 'data': {}}),
                self.url_open(url, json={'event': {}, 'data': {}}),
                self.url_open(url, json={'event': 'payment_intent.status.updated', 'data': []}),
                self.url_open(url, json={
                    'event': 'payment_intent.status.updated', 'data': {'id': [self.intent_id]},
                }),
            ]
        self.assertEqual([r.status_code for r in responses], [200] * len(responses))
        send.assert_not_called()

    @mute_logger(TX_LOGGER)
    def test_refund_event_never_touches_the_payment(self):
        tx = self._create_ziina_transaction()
        with patch(SEND) as send:
            self._webhook('refund.status.updated', self._refund_data(id=self.intent_id))
        send.assert_not_called()
        self.assertEqual(tx.state, 'draft')

    @mute_logger(CONTROLLER_LOGGER)
    def test_webhook_asks_for_retry_when_ziina_unreachable(self):
        tx = self._create_ziina_transaction()
        with patch(SEND, side_effect=ValidationError("Could not establish the connection.")):
            response = self._webhook('payment_intent.status.updated', self._intent())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(tx.state, 'draft')

    # === Refunds === #

    def test_refund_request(self):
        tx = self._create_ziina_transaction(state='done')
        with patch(SEND, side_effect=lambda *a, json=None, **k: self._refund_data(id=json['id'])) as send:
            refund_tx = tx._refund(amount_to_refund=500.0)

        self.assertEqual(send.call_args.args, ('POST', '/refund'))
        payload = send.call_args.kwargs['json']
        self.assertEqual(uuid.UUID(payload['id']).version, 4)
        self.assertEqual(payload, {
            'id': refund_tx.provider_reference,
            'payment_intent_id': self.intent_id,
            'amount': 50000,
            'currency_code': 'AED',
            'test': True,
        })
        self.assertEqual(refund_tx.operation, 'refund')
        self.assertEqual(refund_tx.amount, -500.0)
        self.assertEqual(refund_tx.state, 'pending')

    def test_refund_of_live_payment_is_not_a_test(self):
        self.provider.state = 'enabled'
        tx = self._create_ziina_transaction(state='done')
        with patch(SEND, side_effect=lambda *a, json=None, **k: self._refund_data(id=json['id'])) as send:
            tx._refund(amount_to_refund=500.0)
        self.assertIs(send.call_args.kwargs['json']['test'], False)

    def test_completed_refund_is_done_and_booked_now(self):
        tx = self._create_ziina_transaction(state='done')
        completed = lambda *a, json=None, **k: self._refund_data(id=json['id'], status='completed')
        with patch(SEND, side_effect=completed), patch(TRIGGER, autospec=True) as trigger:
            refund_tx = tx._refund(amount_to_refund=500.0)
        self.assertEqual(refund_tx.state, 'done')
        self.assertIn(self._post_process_cron(), [call.args[0] for call in trigger.call_args_list])

    def test_pending_refund_waits_for_ziina(self):
        tx = self._create_ziina_transaction(state='done')
        pending = lambda *a, json=None, **k: self._refund_data(id=json['id'])
        with patch(SEND, side_effect=pending), patch(TRIGGER, autospec=True) as trigger:
            refund_tx = tx._refund(amount_to_refund=500.0)
        self.assertEqual(refund_tx.state, 'pending')
        self.assertNotIn(self._post_process_cron(), [call.args[0] for call in trigger.call_args_list])

    def test_failed_refund_reports_ziina_error(self):
        tx = self._create_ziina_transaction(state='done')
        failed = lambda *a, json=None, **k: self._refund_data(
            id=json['id'], status='failed', error={'message': "Insufficient balance", 'code': '400'}
        )
        with patch(SEND, side_effect=failed):
            refund_tx = tx._refund(amount_to_refund=500.0)
        self.assertEqual(refund_tx.state, 'error')
        self.assertIn("Insufficient balance", refund_tx.state_message)

    def test_refund_webhook_completes_refund(self):
        tx = self._create_ziina_transaction(state='done')
        refund = self._refund_data(status='completed')
        refund_tx = tx._create_child_transaction(
            500.0, is_refund=True, provider_reference=refund['id'], state='pending'
        )
        with patch(SEND, return_value=refund) as send:
            response = self._webhook('refund.status.updated', refund)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(send.call_args.args, ('GET', f"/refund/{refund['id']}"))
        self.assertEqual(refund_tx.state, 'done')

    def test_refund_in_three_decimal_currency_needs_whole_tens(self):
        kwd = self._enable_currency('KWD')
        tx = self._create_ziina_transaction(state='done', currency_id=kwd.id, amount=10.0)
        with patch(SEND) as send:
            refund_tx = tx._refund(amount_to_refund=1.234)
        send.assert_not_called()
        self.assertEqual(refund_tx.state, 'error')
        self.assertIn('0.010', refund_tx.state_message)

    # === Availability === #

    def test_compatibility_respects_ziina_limits(self):
        kwd = self._enable_currency('KWD')
        self.provider.write({
            'is_published': True,
            'available_currency_ids': [Command.set((self.currency_aed + kwd).ids)],
        })

        def is_compatible(amount, currency):
            return self.provider in self.env['payment.provider']._get_compatible_providers(
                self.company_id, self.partner.id, amount, currency_id=currency.id
            )

        self.assertFalse(is_compatible(1.99, self.currency_aed))
        self.assertTrue(is_compatible(2.0, self.currency_aed))
        self.assertFalse(is_compatible(1.234, kwd))
        self.assertTrue(is_compatible(1.23, kwd))

    def test_supported_currencies(self):
        currencies = self.provider._get_supported_currencies()
        self.assertIn(self.currency_aed, currencies)
        self.assertTrue(set(currencies.mapped('name')) <= set(const.SUPPORTED_CURRENCIES))

    # === Sync cron === #

    def _age(self, tx, hours):
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE payment_transaction SET create_date = create_date - %s * INTERVAL '1 hour'"
            " WHERE id = %s",
            [hours, tx.id],
        )
        tx.invalidate_recordset(['create_date'])

    def _sync(self, **send_kwargs):
        with patch(SEND, **send_kwargs) as send:
            self.env['payment.transaction']._cron_ziina_sync()
        return send

    def test_cron_settles_open_transactions(self):
        tx = self._create_ziina_transaction()
        self._sync(return_value=self._intent())
        self.assertEqual(tx.state, 'done')

    def test_cron_confirms_a_payment_made_after_a_cancel(self):
        tx = self._create_ziina_transaction(state='cancel')
        self._sync(return_value=self._intent())
        self.assertEqual(tx.state, 'done')

    def test_cron_finds_a_refund_whose_answer_got_lost(self):
        tx = self._create_ziina_transaction(state='done')
        refund = self._refund_data(status='completed')
        refund_tx = tx._create_child_transaction(
            500.0, is_refund=True, provider_reference=refund['id'], state='error'
        )
        send = self._sync(return_value=refund)
        self.assertEqual(send.call_args.args, ('GET', f"/refund/{refund['id']}"))
        self.assertEqual(refund_tx.state, 'done')

    @mute_logger(TX_LOGGER)
    def test_cron_moves_past_failing_transactions(self):
        fine = self._create_ziina_transaction(reference='fine')
        odd = self._create_ziina_transaction(reference='odd', provider_reference='intent-odd')
        down = self._create_ziina_transaction(reference='down', provider_reference='intent-down')

        def answer(method, endpoint, reference=None, **kwargs):
            if reference == 'down':
                raise ValidationError("Could not establish the connection to the payment provider.")
            if reference == 'odd':
                return self._intent(id='intent-odd', amount='lots')  # Breaks the amount check.
            return self._intent()

        send = self._sync(side_effect=answer)
        # Newest first: both failures come before the transaction that settles.
        self.assertEqual(
            [call.kwargs['reference'] for call in send.call_args_list], ['down', 'odd', 'fine']
        )
        self.assertEqual((down.state, odd.state, fine.state), ('draft', 'draft', 'done'))

    def test_cron_skips_disabled_providers(self):
        self._create_ziina_transaction()
        self.provider.state = 'disabled'
        self._sync().assert_not_called()

    def test_cron_checks_only_what_can_still_change(self):
        self._create_ziina_transaction(reference='done', state='done')
        self._create_transaction('redirect', reference='never sent')
        for reference, state, hours in (
            ('expired draft', 'draft', 3),
            ('expired cancel', 'cancel', 3),
            ('pending', 'pending', 3),
            ('old pending', 'pending', 49),
        ):
            self._age(self._create_ziina_transaction(reference=reference, state=state), hours)
        send = self._sync(return_value=self._intent(status='pending'))
        self.assertEqual([call.kwargs['reference'] for call in send.call_args_list], ['pending'])

    # === Webhook registration and requests === #

    def test_register_webhook_sets_a_new_secret(self):
        with patch(SEND, return_value={'success': True}) as send:
            self.provider.action_ziina_register_webhook()

        self.assertEqual(send.call_args.args, ('POST', '/webhook'))
        payload = send.call_args.kwargs['json']
        self.assertEqual(payload['url'], self.provider.ziina_webhook_url)
        self.assertTrue(payload['url'].endswith(const.WEBHOOK_ROUTE))
        self.assertEqual(len(payload['secret']), 64)
        self.assertEqual(self.provider.ziina_webhook_secret, payload['secret'])

    def test_refused_webhook_keeps_the_secret(self):
        with patch(SEND, return_value={'success': False, 'error': "Invalid url"}):
            with self.assertRaises(UserError):
                self.provider.action_ziina_register_webhook()
        self.assertEqual(self.provider.ziina_webhook_secret, 'dummy-webhook-secret')

    def test_requests_authenticate_and_hide_the_webhook_secret(self):
        with (
            patch(REQUEST, return_value=self._response(200, {'success': True})) as request,
            self.assertLogs(PROVIDER_LOGGER, level='INFO') as logs,
        ):
            self.provider.action_ziina_register_webhook()

        self.assertEqual(request.call_args.args, ('POST', 'https://api-v2.ziina.com/api/webhook'))
        self.assertEqual(
            request.call_args.kwargs['headers']['Authorization'], 'Bearer dummy-api-key'
        )
        output = '\n'.join(logs.output)
        self.assertNotIn(self.provider.ziina_webhook_secret, output)
        self.assertIn('[REDACTED]', output)

    @mute_logger(PROVIDER_LOGGER)
    def test_unreadable_answer_is_a_failed_request(self):
        for body in (b'<html>Down for maintenance</html>', b'[]'):
            response = self._response(200, None)
            response._content = body
            with patch(REQUEST, return_value=response), self.assertRaises(ValidationError):
                self.provider._send_api_request('GET', f'/payment_intent/{self.intent_id}')

    @mute_logger(PROVIDER_LOGGER)
    def test_api_errors_are_readable(self):
        body = {
            'message': ["amount must not be less than 200", "currency_code must be 3 letters"],
            'error': 'Bad Request',
            'statusCode': 400,
        }
        with patch(REQUEST, return_value=self._response(400, body)):
            with self.assertRaises(ValidationError) as error:
                self.provider._send_api_request('POST', '/payment_intent', json={})
        self.assertIn(
            "amount must not be less than 200; currency_code must be 3 letters",
            str(error.exception),
        )


@tagged('post_install', '-at_install')
class TestZiinaInstall(TransactionCase):

    def test_provider_is_installed_disabled(self):
        provider = self.env.ref('payment_ziina.payment_provider_ziina')
        self.assertEqual(
            (provider.code, provider.state, provider.is_published), ('ziina', 'disabled', False)
        )
        self.assertEqual(provider.redirect_form_view_id, self.env.ref('payment_ziina.redirect_form'))
        codes = provider._get_default_payment_method_codes()
        methods = self.env['payment.method'].with_context(active_test=False).search(
            [('code', 'in', list(codes))]
        )
        self.assertEqual(set(methods.mapped('code')), codes)
