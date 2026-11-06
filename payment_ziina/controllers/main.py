import hashlib
import hmac
import json
import pprint

from werkzeug.exceptions import Forbidden, ServiceUnavailable

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_ziina import const

_logger = get_payment_logger(__name__, const.SENSITIVE_KEYS)


class ZiinaController(http.Controller):

    @http.route(
        const.RETURN_ROUTE, type='http', auth='public', methods=['GET', 'POST'], csrf=False,
        save_session=False,
    )
    def ziina_return_from_checkout(self, reference=None, outcome=None, access_token=None, **kwargs):
        """Update the transaction with its payment intent, fetched from Ziina, after the customer
        comes back from Ziina's payment page.

        The route is flagged with `save_session=False` so that a browser omitting the session
        cookie on this redirect does not get a new session: `/payment/status` then finds the
        customer's own session and transaction.

        :param str reference: The transaction reference, from the return URL.
        :param str outcome: Which of Ziina's return URLs the customer came through.
        :param str access_token: The token signing the reference and the outcome.
        """
        _logger.info("Handling redirection from Ziina for transaction %s (%s).", reference, outcome)
        tx_sudo = request.env['payment.transaction'].sudo()._search_by_reference(
            'ziina', {'reference': reference}
        )
        if not tx_sudo or not tx_sudo.provider_reference or outcome not in const.RETURN_OUTCOMES:
            return request.redirect('/payment/status')
        if not payment_utils.check_access_token(access_token, tx_sudo.reference, outcome):
            _logger.warning("Ignored a return from Ziina with an invalid access token.")
            return request.redirect('/payment/status')

        try:
            payment_data = tx_sudo._ziina_fetch_payment_data()
        except ValidationError:
            # The webhook or the sync cron will update the transaction.
            _logger.exception("Could not fetch the payment intent of %s.", tx_sudo.reference)
        else:
            tx_sudo._process('ziina', dict(payment_data, ziina_outcome=outcome))
        return request.redirect('/payment/status')

    @http.route(const.WEBHOOK_ROUTE, type='http', auth='public', methods=['POST'], csrf=False)
    def ziina_webhook(self):
        """Update the transaction a Ziina notification is about.

        The notification only says which payment intent or refund changed: its status is then
        fetched from Ziina with the provider's key, so a forged notification changes nothing.

        :return: An empty response to acknowledge the notification.
        :raise Forbidden: If the signature does not match the provider's webhook secret.
        :raise ServiceUnavailable: If Ziina cannot be reached, to have the notification sent again.
        """
        body = request.httprequest.get_data()
        try:
            event = json.loads(body)
        except ValueError:
            event = None
        if not isinstance(event, dict):
            _logger.warning("Received an unreadable notification from Ziina.")
            return request.make_json_response('')
        _logger.info("Notification received from Ziina:\n%s", pprint.pformat(event))

        event_name, data = event.get('event'), event.get('data')
        entity = isinstance(event_name, str) and const.HANDLED_WEBHOOK_EVENTS.get(event_name)
        if not entity or not isinstance(data, dict) or not isinstance(data.get('id'), str):
            return request.make_json_response('')

        # Unknown ids are acknowledged: the Ziina account may also serve other shops.
        tx_sudo = request.env['payment.transaction'].sudo()._search_by_reference(
            'ziina', {'id': data.get('id'), 'ziina_entity': entity}
        )
        if tx_sudo:
            self._verify_signature(body, tx_sudo)
            try:
                payment_data = tx_sudo._ziina_fetch_payment_data()
            except ValidationError as error:
                _logger.error("Could not fetch the Ziina data of %s.", tx_sudo.reference)
                raise ServiceUnavailable() from error
            tx_sudo._process('ziina', payment_data)
        return request.make_json_response('')

    @staticmethod
    def _verify_signature(body, tx_sudo):
        """Check the notification's HMAC signature against the provider's webhook secret.

        Without a secret (webhook registered outside Odoo) there is nothing to check; the data is
        fetched from Ziina regardless.

        :param bytes body: The raw body of the notification.
        :param payment.transaction tx_sudo: The transaction the notification is about.
        :raise Forbidden: If the signature is missing or wrong.
        """
        secret = tx_sudo.provider_id.ziina_webhook_secret
        if not secret:
            return
        received = request.httprequest.headers.get('X-Hmac-Signature', '').strip().lower()
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(received.encode(), expected.encode()):
            _logger.warning("Received a Ziina notification with an invalid signature.")
            raise Forbidden()
