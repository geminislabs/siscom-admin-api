-- Usuario técnico para payments.registered_by (pagos manuales desde GAC).
-- Requiere al menos una fila en organizations (usa la más antigua).

INSERT INTO public.users (
    id,
    organization_id,
    cognito_sub,
    email,
    full_name,
    email_verified,
    is_master,
    password_hash
)
SELECT
    gen_random_uuid(),
    o.id,
    'gac-system-registered-by',
    'gac-system-registered-by@internal.geminislabs.io',
    'GAC Sistema (pagos manuales)',
    true,
    false,
    ''
FROM (
    SELECT id FROM public.organizations ORDER BY created_at ASC NULLS LAST LIMIT 1
) AS o
WHERE NOT EXISTS (
    SELECT 1 FROM public.users u
    WHERE u.email = 'gac-system-registered-by@internal.geminislabs.io'
);

SELECT id, email, organization_id
FROM public.users
WHERE email = 'gac-system-registered-by@internal.geminislabs.io';
