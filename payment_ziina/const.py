from odoo.addons.payment.const import SENSITIVE_KEYS as PAYMENT_SENSITIVE_KEYS

# Registering the webhook sends its signing secret; keep it out of the request logs.
SENSITIVE_KEYS = {'secret'}
PAYMENT_SENSITIVE_KEYS.update(SENSITIVE_KEYS)

API_URL = 'https://api-v2.ziina.com/api/'

RETURN_ROUTE = '/payment/ziina/return'
WEBHOOK_ROUTE = '/payment/ziina/webhook'

# Where Ziina's hosted page sends the customer back, one return URL each.
RETURN_OUTCOMES = ('success', 'cancel', 'failure')

# https://docs.ziina.com/supported-currencies
SUPPORTED_CURRENCIES = ('AED', 'BHD', 'EUR', 'GBP', 'INR', 'KWD', 'OMR', 'QAR', 'SAR', 'USD')

# Ziina takes these in multiples of ten minor units: 1.230 OMR, never 1.234 OMR.
THREE_DECIMAL_CURRENCIES = ('BHD', 'KWD', 'OMR')

# https://docs.ziina.com/api-reference/payment-intent/index
MINIMUM_AMOUNT_AED = 2.0

# Ziina's page offers cards, Apple Pay and Google Pay; Odoo shows one "Card" option for it.
DEFAULT_PAYMENT_METHOD_CODES = {'card', 'visa', 'mastercard', 'amex'}

# Minutes a payment intent stays payable. A customer who comes back later gets a new one from
# Pay Now; an abandoned one (or a test one, once the provider is live) cannot be paid later.
INTENT_LIFETIME_MINUTES = 60

# What the sync cron re-checks with Ziina: everything not done for as long as its intent could
# still be paid (lifetime plus a margin), and payments and refunds Ziina reports as pending for
# up to two days. At most SYNC_BATCH_SIZE per run, newest first.
SYNC_RECENT_HOURS = 2
SYNC_PENDING_HOURS = 48
SYNC_BATCH_SIZE = 100

# Ziina's payment intent and refund statuses, by transaction state.
PAYMENT_STATUS_MAPPING = {
    'draft': ('requires_payment_instrument',),
    'pending': ('requires_user_action', 'pending'),
    'done': ('completed',),
    'cancel': ('canceled',),
    'error': ('failed',),
}
REFUND_STATUS_MAPPING = {
    'pending': ('pending',),
    'done': ('completed',),
    'error': ('failed',),
}

# Webhook events and the kind of Ziina object their `data` holds.
HANDLED_WEBHOOK_EVENTS = {
    'payment_intent.status.updated': 'payment_intent',
    'refund.status.updated': 'refund',
}
