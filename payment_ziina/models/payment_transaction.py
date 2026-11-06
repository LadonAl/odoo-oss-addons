import time
import uuid
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import urls

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_ziina import const

_logger = get_payment_logger(__name__, const.SENSITIVE_KEYS)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    # === BUSINESS METHODS - PAYMENT FLOW === #

    def _get_specific_rendering_values(self, processing_values):
        """Override of `payment` to create the Ziina payment intent and redirect to its page.

        Note: self.ensure_one() from `_get_processing_values`
        """
        if self.provider_code != 'ziina':
            return super()._get_specific_rendering_values(processing_values)

        try:
            intent = self._send_api_request(
                'POST', '/payment_intent', json=self._ziina_prepare_payment_intent_payload()
            )
        except ValidationError as error:
            self._set_error(str(error))
            return {}
        if not intent.get('id') or not intent.get('redirect_url'):
            self._set_error(_("Ziina did not return a payment page."))
            return {}

        # Kept now: neither the customer's return nor the webhook carries our reference.
        self.provider_reference = intent['id']

        # A GET form drops the query string of its action; pass it as inputs instead.
        redirect_url = urlsplit(intent['redirect_url'])
        return {
            'api_url': redirect_url._replace(query='').geturl(),
            'url_params': dict(parse_qsl(redirect_url.query)),
        }

    def _ziina_prepare_payment_intent_payload(self):
        """Return the body of the request creating the payment intent.

        :return: The request payload.
        :rtype: dict
        """
        base_url = self.provider_id.get_base_url()
        expiry = time.time() + const.INTENT_LIFETIME_MINUTES * 60
        return {
            'amount': payment_utils.to_minor_currency_units(self.amount, self.currency_id),
            'currency_code': self.currency_id.name,
            'message': self.reference,
            'success_url': self._ziina_get_return_url(base_url, 'success'),
            'cancel_url': self._ziina_get_return_url(base_url, 'cancel'),
            'failure_url': self._ziina_get_return_url(base_url, 'failure'),
            'test': self.provider_id.state == 'test',
            'expiry': str(int(expiry * 1000)),  # Unix time in milliseconds.
        }

    def _ziina_get_return_url(self, base_url, outcome):
        """Return the URL Ziina's page sends the customer to after the given outcome.

        The access token signs the outcome: a guessable transaction reference must not let anyone
        cancel a customer's payment in progress.
        """
        query = urlencode({
            'reference': self.reference,
            'outcome': outcome,
            'access_token': payment_utils.generate_access_token(
                self.reference, outcome, env=self.env
            ),
        })
        return urls.urljoin(base_url, f'{const.RETURN_ROUTE}?{query}')

    def _send_refund_request(self):
        """Override of `payment` to send a refund request to Ziina.

        Note: self.ensure_one() from `_refund`
        """
        if self.provider_code != 'ziina':
            return super()._send_refund_request()

        amount = payment_utils.to_minor_currency_units(-self.amount, self.currency_id)
        if self.currency_id.name in const.THREE_DECIMAL_CURRENCIES and amount % 10:
            raise ValidationError(_(
                "Ziina refunds %s in multiples of 0.010 only.", self.currency_id.name
            ))

        # Kept before the request: should the answer get lost, the refund webhook still finds it.
        self.provider_reference = str(uuid.uuid4())
        source_tx = self.source_transaction_id
        refund_data = self._send_api_request('POST', '/refund', json={
            'id': self.provider_reference,
            'payment_intent_id': source_tx.provider_reference,
            'amount': amount,
            'currency_code': self.currency_id.name,
            'test': not source_tx.is_live,
        })
        self._process('ziina', dict(refund_data, ziina_entity='refund'))

    # === BUSINESS METHODS - PROCESSING === #

    def _ziina_fetch_payment_data(self):
        """Fetch the payment intent, or the refund, of the transaction from Ziina.

        Note: self.ensure_one()

        :return: The payment data, marked with its kind of Ziina object.
        :rtype: dict
        :raise ValidationError: If Ziina cannot be reached or refuses the request.
        """
        self.ensure_one()
        if self.operation == 'refund':
            refund_data = self._send_api_request('GET', f'/refund/{self.provider_reference}')
            return dict(refund_data, ziina_entity='refund')
        return self._send_api_request('GET', f'/payment_intent/{self.provider_reference}')

    @api.model
    def _search_by_reference(self, provider_code, payment_data):
        """Override of `payment` to find the transaction from Ziina's id when the data has no
        reference (webhook notifications)."""
        if provider_code != 'ziina' or payment_data.get('reference'):
            return super()._search_by_reference(provider_code, payment_data)

        ziina_id = payment_data.get('id')
        if not ziina_id:
            _logger.warning("Received Ziina data without an id.")
            return self
        is_refund = payment_data.get('ziina_entity') == 'refund'
        tx = self.search([
            ('provider_code', '=', 'ziina'),
            ('provider_reference', '=', ziina_id),
            ('operation', '=' if is_refund else '!=', 'refund'),
        ], limit=1)
        if not tx:
            _logger.warning("No transaction found matching Ziina id %s.", ziina_id)
        return tx

    def _extract_amount_data(self, payment_data):
        """Override of `payment` to extract the amount and currency from the payment data."""
        if self.provider_code != 'ziina':
            return super()._extract_amount_data(payment_data)
        return {
            'amount': payment_utils.to_major_currency_units(
                payment_data.get('amount') or 0, self.currency_id
            ),
            'currency_code': payment_data.get('currency_code'),
        }

    def _apply_updates(self, payment_data):
        """Override of `payment` to update the transaction based on the payment data."""
        if self.provider_code != 'ziina':
            return super()._apply_updates(payment_data)

        status = payment_data.get('status')
        if self.operation == 'refund':
            self._ziina_apply_refund_status(status, payment_data)
            return

        if not self.is_live and self.provider_id.state == 'enabled':
            # Ziina takes test and live payments with the same key: a test intent paid with a
            # test card after going live must not settle anything.
            self._set_error(_("This Ziina test payment was made after the provider went live."))
            return

        # Written only when it changes: the return route and the webhook often process the same
        # transaction at the same moment, and a needless write makes one of them retry.
        card_brand = (payment_data.get('card_details') or {}).get('card_brand')
        payment_method = card_brand and self.env['payment.method']._get_from_code(card_brand)
        if payment_method and payment_method != self.payment_method_id:
            self.payment_method_id = payment_method

        mapping = const.PAYMENT_STATUS_MAPPING
        if status in mapping['draft']:
            # Nothing paid yet. Returning through the cancel or failure URL still ends the
            # attempt, or the status page would wait for a payment that never comes.
            outcome = payment_data.get('ziina_outcome')
            if outcome == 'cancel':
                self._set_canceled(state_message=_("The customer left Ziina's payment page."))
            elif outcome == 'failure':
                self._set_error(_("The payment failed on Ziina's payment page."))
            elif outcome == 'success':
                self._set_pending()
        elif status in mapping['pending']:
            self._set_pending()
        elif status in mapping['done']:
            # Paid: confirm even if the customer cancelled first and then went back to pay.
            self._set_done(extra_allowed_states=('cancel',))
        elif status in mapping['cancel']:
            self._set_canceled()
        elif status in mapping['error']:
            error = (payment_data.get('latest_error') or {}).get('message')
            self._set_error(_("Ziina: %s", error or _("the payment failed.")))
        else:
            _logger.warning(
                "Received data with invalid payment status %s for transaction %s.",
                status, self.reference,
            )
            self._set_error(_("Received data with invalid payment status: %s.", status))

    def _ziina_apply_refund_status(self, status, refund_data):
        mapping = const.REFUND_STATUS_MAPPING
        if status in mapping['pending']:
            self._set_pending()
        elif status in mapping['done']:
            self._set_done()
            # Nobody browses a refund's status page: book it now.
            self.env.ref('payment.cron_post_process_payment_tx')._trigger()
        elif status in mapping['error']:
            error = (refund_data.get('error') or {}).get('message')
            self._set_error(_("Ziina: %s", error or _("the refund failed.")))
        else:
            _logger.warning(
                "Received data with invalid refund status %s for transaction %s.",
                status, self.reference,
            )
            self._set_error(_("Received data with invalid refund status: %s.", status))

    @api.model
    def _cron_ziina_sync(self):
        """Ask Ziina about the payments and refunds that may still change, for webhooks that
        never came: none registered, or Odoo unreachable through Ziina's three retries.

        That includes cancelled and failed transactions: a customer can go back to Ziina's page
        and pay after all, and a refund whose answer got lost ends in error although Ziina made it.
        """
        now = fields.Datetime.now()
        txs = self.search([
            ('provider_code', '=', 'ziina'),
            ('provider_id.state', '!=', 'disabled'),
            ('provider_reference', '!=', False),
            '|',
            '&',
            ('state', 'in', ('draft', 'pending', 'cancel', 'error')),
            ('create_date', '>=', now - timedelta(hours=const.SYNC_RECENT_HOURS)),
            '&',
            ('state', '=', 'pending'),
            ('create_date', '>=', now - timedelta(hours=const.SYNC_PENDING_HOURS)),
        ], order='id desc', limit=const.SYNC_BATCH_SIZE)
        for tx in txs:
            try:
                with self.env.cr.savepoint():
                    tx._process('ziina', tx._ziina_fetch_payment_data())
            except ValidationError as error:
                _logger.warning("Could not check transaction %s with Ziina: %s", tx.reference, error)
            except Exception:
                # One odd transaction must not keep the others from being checked.
                _logger.exception("Could not update transaction %s from Ziina.", tx.reference)
