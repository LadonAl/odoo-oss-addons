# Payment Provider: Ziina

Lets customers pay invoices (and anything else Odoo takes online payments for:
quotations, website checkout, payment links) through [Ziina](https://ziina.com),
the UAE business payment platform. The customer picks **Card** in Odoo's payment
form, pays on Ziina's hosted page (card, Apple Pay or Google Pay) and comes back
to Odoo, which confirms the payment with Ziina and books it on the invoice.
Refunds, full or partial, are sent from Odoo.

Installing the addon creates a **disabled** Ziina provider in every main
company (branches share their parent's): nothing changes for customers until
someone enters an API key and enables it.

## Requirements

* Odoo 19.0 (built and tested on Community). The addon depends only on
  `payment`; invoice payments, the **Payment Journal** setting and refunds come
  from Odoo's `account_payment`, which installs itself with Invoicing.
* A verified Ziina business account. Ziina onboards UAE businesses. In a
  multi-company database, set up the provider in the company that owns the
  Ziina account and leave it disabled in the others.
* The account's API key. On [ziina.com/business/connect](https://ziina.com/business/connect)
  choose **Other builder or custom**, enter the phone number, the OTP and an email.
  Ziina shows the key **once**: paste it straight into Odoo (step 3), or into a
  password manager. Anyone holding it can create payments and refunds on the account.
* Odoo reachable from the internet over `https://`, for Ziina's redirects and
  webhook.

## Set it up

1. Switch Odoo to the company that owns the Ziina account (company switcher, top right).
2. Open **Invoicing → Configuration → Online Payments → Payment Providers → Ziina**.
3. **Credentials** tab: paste the key into **API Key**, then save.
4. Press **Register Webhook**. Odoo sets the account's webhook to the **Webhook URL**
   shown above the button, with a fresh signing secret, so Ziina reports each
   payment and refund the moment it changes. Ziina keeps **one webhook per
   account**: if the same Ziina account also runs a Shopify or WooCommerce shop,
   registering here takes the webhook away from that shop. The URL must be the
   public `https://` address of this Odoo (in developer mode: Settings →
   Technical → System Parameters → `web.base.url`); press the button again if
   that address changes.
5. **Configuration** tab: check **Payment Journal** (the journal Odoo books Ziina
   payments on; a dedicated bank journal named "Ziina" makes it easy to match the
   balance with Ziina's payouts) and, if wanted, **Maximum Amount** or **Countries**.
6. Set **State** to **Test Mode**. Odoo unpublishes the provider in Test Mode
   (the button at the top of the form reads **Unpublished**): customers don't
   see it, but logged-in Odoo users do. Keep it that way while testing: a
   customer paying a real invoice with a test card would mark it paid with no
   money received.
7. Test, logged in: create an AED invoice to a test customer, post it, open its
   portal page (*Preview* on the invoice), press **Pay Now**, choose **Card** and
   pay on Ziina's page with the test card `4242 4242 4242 4242`, any future expiry
   and any CVV. No money moves. The invoice shows *Paid*; its payment (Invoicing →
   Customers → Payments) has a **Refund** button to try a refund. Afterwards reset
   that invoice and payment, or cancel them, so the books stay clean.
8. Go live: set **State** to **Enabled** and save. Odoo publishes the provider
   with it (the button now reads **Published**; don't press it, that would
   unpublish it). The same key now takes real payments. A test payment
   completed after this point is refused: it lands in error instead of
   settling anything.

To stop taking payments, set the state back to **Disabled** (or press
**Published** to unpublish it).

## What customers see

One payment option, **Card**, with the Visa, Mastercard and American Express
logos and "Secured by Ziina". Ziina's page also offers Apple Pay and Google Pay
on devices that support them. After paying they land back on the invoice, marked
*Paid*. If they cancel, or the card is declined, they land back on the invoice
with **Pay Now** available to try again.

Ziina is hidden from the payment form when it would refuse the amount:

* AED amounts below 2.00 (Ziina's minimum);
* BHD, KWD and OMR amounts that are not a multiple of 0.010.

Currencies Ziina charges in: AED, BHD, EUR, GBP, INR, KWD, OMR, QAR, SAR and USD.
Ziina converts foreign currencies to AED at the real-time rate when the customer
pays; Odoo records the payment in the invoice's currency.

## How it works

1. **Pay**: Odoo creates a Ziina *payment intent* for the amount (in fils), with
   three return URLs and a one-hour expiry, and sends the customer to its
   `redirect_url`. In Test Mode the intent is created with `test: true`. A
   customer who comes back after the hour just presses Pay Now again.
2. **Return**: Ziina sends the customer to the success, cancel or failure URL.
   Each carries the transaction reference and a token that signs it, so a
   guessed reference cannot cancel someone else's payment. Odoo then **fetches
   the intent from Ziina** and updates the transaction:

   | Ziina status | Odoo transaction |
   |---|---|
   | `completed` | Confirmed (also after a cancel: the customer may go back and pay) |
   | `pending`, `requires_user_action` | Pending |
   | `failed` | Error, with Ziina's reason ("Your card was declined.") |
   | `canceled` | Cancelled |
   | `requires_payment_instrument` (nothing paid) | Cancelled after *cancel*, Error after *failure*, Pending after *success* |

3. **Webhook**: Ziina also posts `payment_intent.status.updated` and
   `refund.status.updated` to `/payment/ziina/webhook`. Odoo checks the
   `X-Hmac-Signature` against the stored secret (there is always one when the
   webhook was registered from Odoo), then again fetches the intent or refund
   from Ziina rather than trusting the posted body. Notifications about
   payments Odoo does not know (another shop on the same account) are acknowledged
   and ignored. Ziina's published webhook IP addresses are not checked: behind a
   reverse proxy the address Odoo sees is not reliable, and the re-fetch makes a
   forged notification harmless anyway.
4. **Safety net**: the scheduled action *Ziina: check open payments and refunds*
   asks Ziina every 15 minutes about every transaction that may still change:
   anything not confirmed from the last 2 hours (including cancelled and failed
   ones, since a customer can go back to Ziina's page and pay after all) and
   anything Ziina still calls pending from the last 48 hours, up to 100 a run.
   It catches payments whose webhook never arrived: no webhook registered, or
   Odoo down through Ziina's three retries.
5. **Refunds**: the **Refund** button on a Ziina payment (Invoicing → Customers →
   Payments) sends `POST /refund` for the amount chosen. The refund shows as
   pending until Ziina completes it, then Odoo books the outgoing payment. If a
   refund ends in error with *Could not establish the connection*, Ziina may
   still have made it: check the Ziina app (or wait for the next check) before
   refunding again.

Odoo books the gross amount. Ziina's fees come off its payouts, so record them
when reconciling the payout.

The API key and the webhook secret are readable by administrators only and
stay out of the payment logs (the key travels in a request header, which is
not logged; the secret is redacted). Both are cleared when a database is
neutralized (a copy for testing or staging).

## Not supported

* Saved cards (tokenization), authorize-then-capture, and Ziina's embedded
  checkout (it needs Ziina to whitelist the domain first): the hosted page covers
  cards, Apple Pay and Google Pay.
* Two Odoo providers on one Ziina account (one webhook per account): register the
  webhook from one of them only.

## Tests

The tests replace Ziina with canned answers, so they run without network
access or a Ziina account:

```bash
odoo -d test_db -i payment_ziina --test-enable --test-tags /payment_ziina --stop-after-init
```

API reference: [docs.ziina.com](https://docs.ziina.com) (payment intents, refunds, webhooks).

## License and credits

LGPL-3.0, full text in [`LICENSES/LGPL-3.0.txt`](../LICENSES/LGPL-3.0.txt).

Made by [LadonAl Labz](https://github.com/LadonAl). Not an official Ziina
product and not endorsed by Ziina. The Ziina name and logo belong to Ziina and
are used only to identify the service.
