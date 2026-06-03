-- Columna requerida por el modelo Subscription y pagos manuales.
-- Ejecutar en la BD de siscom-admin-api si aún no aplicaste payment-gateway.sql completo.

ALTER TABLE public.subscriptions
  ADD COLUMN IF NOT EXISTS active_units int NOT NULL DEFAULT 1;
