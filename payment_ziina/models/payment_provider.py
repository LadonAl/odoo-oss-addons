import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import urls

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_ziina import const

_logger = get_payment_logger(__name__, const.SENSITIVE_KEYS)


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(selection_add=[('ziina', "Ziina")], ondelete={'ziina': 'set default'})
    ziina_api_key = fields.Char(
        string="Ziina API Key",
        help="Generated at ziina.com/business/connect ('Other builder or custom'). Ziina shows it"
             " only once. The same key serves test and live payments.",
        required_if_provider='ziina',
        copy=False,
        groups='base.group_system',
    )
    ziina_webhook_secret = fields.Char(
        string="Ziina Webhook Secret",
        help="Signs the notifications Ziina sends to the webhook. 'Register Webhook' sets it.",
        copy=False,
        groups='base.group_system',
    )
    ziina_webhook_url = fields.Char(
        string="Ziina Webhook URL", compute='_compute_ziina_webhook_url'
    )

    # === COMPUTE METHODS === #

    def _compute_ziina_webhook_url(self):
        for provider in self:
            provider.ziina_webhook_url = urls.urljoin(provider.get_base_url(), const.WEBHOOK_ROUTE)

    def _compute_feature_support_fields(self):
        """Override of `payment` to enable refunds."""
        super()._compute_feature_support_fields()
        self.filtered(lambda p: p.code == 'ziina').support_refund = 'partial'

    def _get_supported_currencies(self):
        """Override of `payment` to return the currencies Ziina charges in."""
        supported_currencies = super()._get_supported_currencies()
        if self.code == 'ziina':
            supported_currencies = supported_currencies.filtered(
                lambda c: c.name in const.SUPPORTED_CURRENCIES
            )
        return supported_currencies

    # === CRUD METHODS === #

    def _get_default_payment_method_codes(self):
        """Override of `payment` to return the default payment method codes."""
        self.ensure_one()
        if self.code != 'ziina':
            return super()._get_default_payment_method_codes()
        return const.DEFAULT_PAYMENT_METHOD_CODES

    # === ACTION METHODS === #

    def action_ziina_register_webhook(self):
        """Point the Ziina account's webhook at this database, with a new signing secret.

        Ziina keeps one webhook per account: this replaces whatever URL was set before.

        :return: A notification action.
        :rtype: dict
        """
        self.ensure_one()
        if not self.ziina_api_key:
            raise UserError(_("Enter the Ziina API key first."))

        secret = secrets.token_hex(32)
        response = self._send_api_request(
            'POST', '/webhook', json={'url': self.ziina_webhook_url, 'secret': secret}
        )
        if not response.get('success'):
            raise UserError(_(
                "Ziina did not accept the webhook: %s", response.get('error') or _("no reason given")
            ))
        self.ziina_webhook_secret = secret
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _("Ziina now sends payment updates to %s.", self.ziina_webhook_url),
            },
        }

    # === BUSINESS METHODS === #

    @api.model
    def _get_compatible_providers(
        self, company_id, partner_id, amount, *args, currency_id=None, report=None, **kwargs
    ):
        """Override of `payment` to hide Ziina for amounts its API would refuse."""
        providers = super()._get_compatible_providers(
            company_id, partner_id, amount, *args, currency_id=currency_id, report=report, **kwargs
        )

        currency = self.env['res.currency'].browse(currency_id).exists()
        ziina_providers = providers.filtered(lambda p: p.code == 'ziina')
        if not (ziina_providers and currency and amount):
            return providers

        reason = None
        if currency.name == 'AED' and currency.compare_amounts(amount, const.MINIMUM_AMOUNT_AED) < 0:
            reason = _("below Ziina's minimum of 2 AED")
        elif (
            currency.name in const.THREE_DECIMAL_CURRENCIES
            and payment_utils.to_minor_currency_units(amount, currency) % 10
        ):
            reason = _("Ziina takes %s amounts in multiples of 0.010 only", currency.name)
        if reason:
            providers -= ziina_providers
            payment_utils.add_to_report(report, ziina_providers, available=False, reason=reason)
        return providers

    # === REQUEST HELPERS === #

    def _build_request_url(self, endpoint, **kwargs):
        """Override of `payment` to build the request URL."""
        if self.code != 'ziina':
            return super()._build_request_url(endpoint, **kwargs)
        return urls.urljoin(const.API_URL, endpoint.strip('/'))

    def _build_request_headers(self, method, endpoint, payload, **kwargs):
        """Override of `payment` to authenticate with the API key."""
        if self.code != 'ziina':
            return super()._build_request_headers(method, endpoint, payload, **kwargs)
        return {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.ziina_api_key}',
        }

    def _parse_response_content(self, response, **kwargs):
        """Override of `payment` to treat an unreadable answer like a failed request.

        Every caller then handles it: the return route still redirects, the webhook asks Ziina to
        retry, and the sync cron moves on to the next transaction.
        """
        if self.code != 'ziina':
            return super()._parse_response_content(response, **kwargs)
        try:
            content = response.json()
        except ValueError:
            content = None
        if not isinstance(content, dict):
            raise ValidationError(_("Ziina sent an answer Odoo cannot read."))
        return content

    def _parse_response_error(self, response):
        """Override of `payment` to read Ziina's error message.

        Ziina answers `{"message": "...", "statusCode": 400}`; validation errors list one message
        per field.
        """
        if self.code != 'ziina':
            return super()._parse_response_error(response)
        message = response.json().get('message')
        if isinstance(message, list):
            message = '; '.join(str(m) for m in message)
        return message or response.text
