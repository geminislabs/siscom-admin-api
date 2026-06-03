-- Migración local: esquema gateway (invoices + payments nuevos).
-- Para BD dev que aún tiene payments legacy (columna status/method).
-- Idempotente donde es posible.

BEGIN;

-- ── ENUMs ───────────────────────────────────────────────────────
DO $$ BEGIN
    CREATE TYPE public.invoice_status AS ENUM (
        'DRAFT', 'OPEN', 'PAID', 'PAST_DUE', 'VOID', 'UNCOLLECTIBLE'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE public.payment_status AS ENUM (
        'PENDING', 'REQUIRES_ACTION', 'PROCESSING', 'SUCCESS',
        'FAILED', 'CANCELED', 'DISPUTED', 'REFUNDED', 'PARTIALLY_REFUNDED'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN ALTER TYPE public.payment_gateway ADD VALUE 'conekta';
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TYPE public.payment_gateway ADD VALUE 'mercadopago';
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TYPE public.payment_gateway ADD VALUE 'paypal';
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TYPE public.payment_gateway ADD VALUE 'manual';
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TYPE public.payment_method_type ADD VALUE 'manual';
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ── invoices ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.invoices (
    id                    uuid                   NOT NULL DEFAULT gen_random_uuid(),
    account_id            uuid                   NOT NULL,
    organization_id       uuid                   NOT NULL,
    subscription_id       uuid                   NULL,
    gateway               public.payment_gateway NULL,
    external_invoice_id   text                   NULL,
    invoice_number        text                   NOT NULL,
    invoice_status        public.invoice_status  NOT NULL DEFAULT 'DRAFT',
    subtotal              numeric(10,2)          NOT NULL,
    discount_amount       numeric(10,2)          NOT NULL DEFAULT 0,
    tax_amount            numeric(10,2)          NOT NULL DEFAULT 0,
    total_amount          numeric(10,2)          NOT NULL,
    currency              text                   NOT NULL DEFAULT 'MXN',
    due_at                timestamptz            NULL,
    paid_at               timestamptz            NULL,
    voided_at             timestamptz            NULL,
    invoice_pdf_url       text                   NULL,
    cfdi_uuid             text                   NULL,
    metadata              jsonb                  NOT NULL DEFAULT '{}',
    created_at            timestamptz            NOT NULL DEFAULT now(),
    updated_at            timestamptz            NOT NULL DEFAULT now(),
    CONSTRAINT inv_pkey          PRIMARY KEY (id),
    CONSTRAINT inv_number_key    UNIQUE (invoice_number),
    CONSTRAINT inv_account_fkey  FOREIGN KEY (account_id)
        REFERENCES public.accounts(id),
    CONSTRAINT inv_org_fkey      FOREIGN KEY (organization_id)
        REFERENCES public.organizations(id),
    CONSTRAINT inv_sub_fkey      FOREIGN KEY (subscription_id)
        REFERENCES public.subscriptions(id)
);

CREATE INDEX IF NOT EXISTS idx_inv_account ON public.invoices (account_id);
CREATE INDEX IF NOT EXISTS idx_inv_org     ON public.invoices (organization_id);
CREATE INDEX IF NOT EXISTS idx_inv_sub     ON public.invoices (subscription_id);
CREATE INDEX IF NOT EXISTS idx_inv_status  ON public.invoices (invoice_status);

-- ── payments: renombrar legacy si aún tiene columna "status" ───
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'payments' AND column_name = 'status'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'payments_legacy'
    ) THEN
        ALTER TABLE public.orders DROP CONSTRAINT IF EXISTS orders_payment_id_fkey;
        ALTER TABLE public.payments RENAME TO payments_legacy;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.payments (
    id                      uuid                       NOT NULL DEFAULT gen_random_uuid(),
    invoice_id              uuid                       NOT NULL,
    account_id              uuid                       NOT NULL,
    organization_id         uuid                       NOT NULL,
    gateway                 public.payment_gateway     NOT NULL,
    gateway_payment_id      text                       NULL,
    idempotency_key         text                       NULL,
    payment_method_type     public.payment_method_type NOT NULL,
    payment_method_id       uuid                       NULL,
    payment_method_meta     jsonb                      NOT NULL DEFAULT '{}',
    amount                  numeric(10,2)              NOT NULL,
    currency                text                       NOT NULL DEFAULT 'MXN',
    refunded_amount         numeric(10,2)              NOT NULL DEFAULT 0,
    installments            int                        NULL,
    installment_amount      numeric(10,2)              NULL,
    payment_status          public.payment_status      NOT NULL DEFAULT 'PENDING',
    authorized_at           timestamptz                NULL,
    captured_at             timestamptz                NULL,
    initiated_at            timestamptz                NULL,
    succeeded_at            timestamptz                NULL,
    failed_at               timestamptz                NULL,
    canceled_at             timestamptz                NULL,
    refunded_at             timestamptz                NULL,
    failure_code            text                       NULL,
    failure_message         text                       NULL,
    is_disputed             bool                       NOT NULL DEFAULT false,
    dispute_id              text                       NULL,
    dispute_reason          text                       NULL,
    dispute_status          text                       NULL,
    dispute_due_at          timestamptz                NULL,
    dispute_resolved_at     timestamptz                NULL,
    risk_score              int                        NULL,
    risk_level              text                       NULL,
    client_ip               inet                       NULL,
    device_session_id       text                       NULL,
    provider_response       jsonb                      NULL,
    registered_by           uuid                       NULL,
    registration_notes      text                       NULL,
    metadata                jsonb                      NOT NULL DEFAULT '{}',
    created_at              timestamptz                NOT NULL DEFAULT now(),
    updated_at              timestamptz                NOT NULL DEFAULT now(),
    CONSTRAINT pay_pkey                PRIMARY KEY (id),
    CONSTRAINT pay_refunded_chk        CHECK (refunded_amount >= 0 AND refunded_amount <= amount),
    CONSTRAINT pay_manual_chk          CHECK (
        gateway::text != 'manual' OR registered_by IS NOT NULL
    ),
    CONSTRAINT pay_invoice_fkey        FOREIGN KEY (invoice_id)
        REFERENCES public.invoices(id),
    CONSTRAINT pay_account_fkey        FOREIGN KEY (account_id)
        REFERENCES public.accounts(id),
    CONSTRAINT pay_org_fkey            FOREIGN KEY (organization_id)
        REFERENCES public.organizations(id),
    CONSTRAINT pay_method_fkey         FOREIGN KEY (payment_method_id)
        REFERENCES public.payment_methods(id) ON DELETE SET NULL,
    CONSTRAINT pay_registered_by_fkey  FOREIGN KEY (registered_by)
        REFERENCES public.users(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pay_gateway_id
    ON public.payments (gateway_payment_id) WHERE gateway_payment_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_pay_idempotency
    ON public.payments (idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_pay_invoice ON public.payments (invoice_id);
CREATE INDEX IF NOT EXISTS idx_pay_account ON public.payments (account_id);
CREATE INDEX IF NOT EXISTS idx_pay_status  ON public.payments (payment_status);

COMMIT;
