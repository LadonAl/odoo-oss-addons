-- remove the Ziina credentials from neutralized databases
UPDATE payment_provider
   SET ziina_api_key = NULL,
       ziina_webhook_secret = NULL;
