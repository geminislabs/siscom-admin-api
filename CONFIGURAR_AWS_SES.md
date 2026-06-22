# 🔧 Configurar AWS SES para Envío de Emails

## ⚠️ Problemas Detectados

Tu configuración actual tiene estos problemas:

1. ❌ **Usuario IAM sin permisos**: `github-actions` no tiene permisos de SES
2. ❌ **Emails no verificados**: `noreply@geminislabs.com` y `contacto@geminislabs.com` no están verificados en SES

## 🛠️ Solución: Opción 1 - Verificar Emails en SES (Recomendado)

### Paso 1: Verificar los emails en AWS SES

Ejecuta estos comandos en tu terminal:

```bash
# Verificar el email remitente (FROM)
aws ses verify-email-identity \
  --email-address noreply@geminislabs.com \
  --region us-east-1

# Verificar el email de contacto (TO)
aws ses verify-email-identity \
  --email-address contacto@geminislabs.com \
  --region us-east-1
```

### Paso 2: Confirmar los emails

AWS SES enviará un email de verificación a cada dirección. **Debes hacer clic en el enlace de verificación** en ambos emails.

### Paso 3: Agregar permisos al usuario IAM

El usuario `github-actions` necesita permisos para enviar emails. Ejecuta:

```bash
# Crear el archivo de política
cat > /tmp/ses-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ses:SendEmail",
        "ses:SendRawEmail"
      ],
      "Resource": "*"
    }
  ]
}
EOF

# Aplicar la política al usuario
aws iam put-user-policy \
  --user-name github-actions \
  --policy-name SESSendEmailPolicy \
  --policy-document file:///tmp/ses-policy.json

echo "✅ Permisos agregados al usuario github-actions"
```

### Paso 4: Reiniciar el servidor

```bash
# Detén el servidor con Ctrl+C
# Luego reinicia:
uvicorn app.main:app --reload
```

### Paso 5: Probar nuevamente

```bash
curl --location 'http://localhost:8000/api/v1/contact/send-message' \
--header 'Content-Type: application/json' \
--data-raw '{
  "nombre": "Juan Pérez",
  "correo_electronico": "juan@example.com",
  "telefono": "+52 123 456 7890",
  "mensaje": "Estoy interesado en sus servicios..."
}'
```

---

## 🛠️ Solución: Opción 2 - Usar IAM Role (Si estás en EC2)

Si tu aplicación corre en EC2, es mejor usar un IAM Role en lugar de credenciales:

### Paso 1: Crear un IAM Role

```bash
# Crear el trust policy
cat > /tmp/trust-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ec2.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# Crear el role
aws iam create-role \
  --role-name EC2-SES-Role \
  --assume-role-policy-document file:///tmp/trust-policy.json
```

### Paso 2: Agregar permisos de SES al role

```bash
# Crear política de SES
cat > /tmp/ses-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ses:SendEmail",
        "ses:SendRawEmail",
        "ses:VerifyEmailIdentity"
      ],
      "Resource": "*"
    }
  ]
}
EOF

# Crear la política
aws iam create-policy \
  --policy-name SES-SendEmail-Policy \
  --policy-document file:///tmp/ses-policy.json

# Adjuntar la política al role (reemplaza ACCOUNT_ID con tu número de cuenta)
aws iam attach-role-policy \
  --role-name EC2-SES-Role \
  --policy-arn arn:aws:iam::535002870158:policy/SES-SendEmail-Policy
```

### Paso 3: Asignar el role a tu instancia EC2

```bash
# Crear instance profile
aws iam create-instance-profile --instance-profile-name EC2-SES-Profile

# Agregar el role al profile
aws iam add-role-to-instance-profile \
  --instance-profile-name EC2-SES-Profile \
  --role-name EC2-SES-Role

# Asociar el profile a tu instancia (reemplaza INSTANCE_ID)
aws ec2 associate-iam-instance-profile \
  --instance-id i-xxxxxxxxxxxxxxxxx \
  --iam-instance-profile Name=EC2-SES-Profile
```

### Paso 4: Remover credenciales del .env

Si usas IAM Role, puedes comentar estas líneas en el `.env`:

```bash
# AWS_ACCESS_KEY_ID=AKIAEXAMPLEKEY
# AWS_SECRET_ACCESS_KEY=your-secret-access-key
```

---

## 🛠️ Solución: Opción 3 - Usar Sandbox Mode (Solo Desarrollo)

Si solo necesitas probar en desarrollo:

### Paso 1: Verificar emails de prueba

En Sandbox mode, debes verificar **ambos** emails (remitente y destinatario):

```bash
# Email remitente
aws ses verify-email-identity \
  --email-address noreply@geminislabs.com \
  --region us-east-1

# Email destinatario (para pruebas usa tu email personal)
aws ses verify-email-identity \
  --email-address tu-email-personal@gmail.com \
  --region us-east-1
```

### Paso 2: Actualizar CONTACT_EMAIL temporalmente

Para pruebas, usa tu email personal:

```bash
# En el .env, cambiar temporalmente:
CONTACT_EMAIL=tu-email-personal@gmail.com
```

---

## 📋 Verificar Estado de Verificación

Para ver qué emails están verificados:

```bash
aws ses list-identities --region us-east-1

# Ver detalles de un email específico
aws ses get-identity-verification-attributes \
  --identities noreply@geminislabs.com contacto@geminislabs.com \
  --region us-east-1
```

---

## 🚀 Mover a Producción (Salir del Sandbox)

Para enviar emails a **cualquier dirección** sin verificar:

1. Ve a [AWS SES Console](https://console.aws.amazon.com/ses/)
2. En el menú lateral, selecciona **"Account dashboard"**
3. Haz clic en **"Request production access"**
4. Completa el formulario:
   - **Mail type**: Transactional
   - **Website URL**: Tu sitio web
   - **Use case description**:
     ```
     Necesitamos enviar correos transaccionales para:
     - Verificación de cuentas de usuario
     - Recuperación de contraseñas
     - Mensajes de contacto desde el formulario web
     - Invitaciones a usuarios
     ```
5. Espera la aprobación (usualmente 24-48 horas)

---

## ✅ Checklist Final

Antes de que funcione en producción:

- [ ] `SES_FROM_EMAIL` configurado con email real
- [ ] `CONTACT_EMAIL` configurado con email real
- [ ] Ambos emails verificados en AWS SES
- [ ] Usuario IAM tiene permisos de `ses:SendEmail`
- [ ] (Opcional) Cuenta fuera del Sandbox mode
- [ ] Servidor reiniciado después de cambios en `.env`

---

## 🔍 Verificar Configuración Actual

Ejecuta estos comandos para verificar:

```bash
# Ver emails verificados
aws ses list-verified-email-addresses --region us-east-1

# Ver permisos del usuario
aws iam get-user-policy \
  --user-name github-actions \
  --policy-name SESSendEmailPolicy

# Probar envío de email
aws ses send-email \
  --from noreply@geminislabs.com \
  --destination "ToAddresses=contacto@geminislabs.com" \
  --message "Subject={Data=Test},Body={Text={Data=Test}}" \
  --region us-east-1
```

---

## 📞 Soporte

Si sigues teniendo problemas:

1. Revisa los logs del servidor
2. Verifica en AWS SES Console → Email sending → Sending statistics
3. Revisa AWS CloudWatch Logs para errores de SES
4. Consulta la documentación: [docs/guides/email-configuration.md](docs/guides/email-configuration.md)
