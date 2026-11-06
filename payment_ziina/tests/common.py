from odoo.addons.payment.tests.common import PaymentCommon


class ZiinaCommon(PaymentCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.currency_aed = cls._enable_currency('AED')
        cls.provider = cls._prepare_provider('ziina', update_values={
            'ziina_api_key': 'dummy-api-key',
            'ziina_webhook_secret': 'dummy-webhook-secret',
        })
        cls.currency = cls.currency_aed
        cls.payment_method_id = cls.env.ref('payment.payment_method_card').id

        cls.intent_id = '3fa85f64-5717-4562-b3fc-2c963f66afa6'
        cls.intent = {  # As in https://docs.ziina.com/api-reference/webhook/index
            'id': cls.intent_id,
            'account_id': 'b8d4c3a2-0f1e-4d5c-9b8a-7f6e5d4c3b2a',
            'amount': 111111,  # 1111.11 AED in fils.
            'tip_amount': 0,
            'vat_amount': 0,
            'currency_code': 'AED',
            'created_at': '1712345678901',
            'status': 'completed',
            'operation_id': '5b1d2f3e-4c5d-6e7f-8a9b-0c1d2e3f4a5b',
            'redirect_url': f'https://pay.ziina.com/payment_intent/{cls.intent_id}?lang=en',
            'settled': {'amount': 111111, 'tip_amount': 0, 'vat_amount': 0, 'currency_code': 'AED'},
            'card_details': {'card_last_four': '6789', 'card_brand': 'mastercard'},
        }

    def _intent(self, **values):
        return dict(self.intent, **values)

    def _create_ziina_transaction(self, **values):
        return self._create_transaction('redirect', **{'provider_reference': self.intent_id, **values})
