#!/bin/bash

# Script de prueba para los nuevos endpoints de autenticación
# 
# Uso:
#   ./test_auth_endpoints.sh <comando> [argumentos]
#
# Comandos:
#   change-password <email> <old_password> <new_password>
#   resend-verification <email>
#   confirm-email <token>
#   full-verification-flow <email>

set -e

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuración
API_URL="http://localhost:8000/api/v1"

# Función para mostrar ayuda
show_help() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  Test: Endpoints de Autenticación${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    echo "Uso: $0 <comando> [argumentos]"
    echo ""
    echo "Comandos disponibles:"
    echo ""
    echo -e "  ${GREEN}change-password${NC} <email> <old_pwd> <new_pwd>"
    echo "    Cambia la contraseña de un usuario autenticado"
    echo ""
    echo -e "  ${GREEN}resend-verification${NC} <email>"
    echo "    Reenvía el correo de verificación"
    echo ""
    echo -e "  ${GREEN}confirm-email${NC} <token>"
    echo "    Confirma el email con un token"
    echo ""
    echo -e "  ${GREEN}full-verification-flow${NC} <email>"
    echo "    Ejecuta el flujo completo de verificación"
    echo ""
    echo "Ejemplos:"
    echo "  $0 change-password usuario@example.com OldPwd123! NewPwd456!"
    echo "  $0 resend-verification usuario@example.com"
    echo "  $0 confirm-email example-email-token"
    echo "  $0 full-verification-flow usuario@example.com"
    echo ""
}

# ===========================================
# Comando: change-password
# ===========================================
change_password() {
    EMAIL="$1"
    OLD_PASSWORD="$2"
    NEW_PASSWORD="$3"
    
    if [ -z "$EMAIL" ] || [ -z "$OLD_PASSWORD" ] || [ -z "$NEW_PASSWORD" ]; then
        echo -e "${RED}Error: Faltan argumentos${NC}"
        echo "Uso: $0 change-password <email> <old_password> <new_password>"
        exit 1
    fi
    
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  TEST: Cambiar Contraseña${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    echo -e "${YELLOW}Email:${NC} $EMAIL"
    echo -e "${YELLOW}Contraseña actual:${NC} $OLD_PASSWORD"
    echo -e "${YELLOW}Nueva contraseña:${NC} $NEW_PASSWORD"
    echo ""
    
    # 1. Login para obtener access_token
    echo -e "${CYAN}1. Autenticando usuario...${NC}"
    LOGIN_RESPONSE=$(curl -s -X POST "$API_URL/auth/login" \
      -H "Content-Type: application/json" \
      -d "{\"email\": \"$EMAIL\", \"password\": \"$OLD_PASSWORD\"}")
    
    if echo "$LOGIN_RESPONSE" | jq -e '.access_token' > /dev/null 2>&1; then
        ACCESS_TOKEN=$(echo "$LOGIN_RESPONSE" | jq -r '.access_token')
        echo -e "${GREEN}✓ Login exitoso${NC}"
    else
        echo -e "${RED}✗ Error en login:${NC}"
        echo "$LOGIN_RESPONSE" | jq .
        exit 1
    fi
    
    echo ""
    
    # 2. Cambiar contraseña
    echo -e "${CYAN}2. Cambiando contraseña...${NC}"
    CHANGE_RESPONSE=$(curl -s -X PATCH "$API_URL/auth/password" \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer $ACCESS_TOKEN" \
      -d "{\"old_password\": \"$OLD_PASSWORD\", \"new_password\": \"$NEW_PASSWORD\"}")
    
    echo -e "${GREEN}Respuesta:${NC}"
    echo "$CHANGE_RESPONSE" | jq .
    
    if echo "$CHANGE_RESPONSE" | jq -e '.message' > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Contraseña cambiada exitosamente${NC}"
    else
        echo -e "${RED}✗ Error al cambiar contraseña${NC}"
        exit 1
    fi
    
    echo ""
    
    # 3. Verificar login con nueva contraseña
    echo -e "${CYAN}3. Verificando login con nueva contraseña...${NC}"
    VERIFY_RESPONSE=$(curl -s -X POST "$API_URL/auth/login" \
      -H "Content-Type: application/json" \
      -d "{\"email\": \"$EMAIL\", \"password\": \"$NEW_PASSWORD\"}")
    
    if echo "$VERIFY_RESPONSE" | jq -e '.access_token' > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Login con nueva contraseña exitoso${NC}"
    else
        echo -e "${RED}✗ Error en login con nueva contraseña${NC}"
        echo "$VERIFY_RESPONSE" | jq .
        exit 1
    fi
    
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  ✓ Prueba completada exitosamente${NC}"
    echo -e "${GREEN}========================================${NC}"
}

# ===========================================
# Comando: resend-verification
# ===========================================
resend_verification() {
    EMAIL="$1"
    
    if [ -z "$EMAIL" ]; then
        echo -e "${RED}Error: Falta el email${NC}"
        echo "Uso: $0 resend-verification <email>"
        exit 1
    fi
    
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  TEST: Reenviar Verificación${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    echo -e "${YELLOW}Email:${NC} $EMAIL"
    echo ""
    
    # Reenviar verificación
    echo -e "${CYAN}1. Solicitando reenvío de verificación...${NC}"
    RESEND_RESPONSE=$(curl -s -X POST "$API_URL/auth/resend-verification" \
      -H "Content-Type: application/json" \
      -d "{\"email\": \"$EMAIL\"}")
    
    echo -e "${GREEN}Respuesta:${NC}"
    echo "$RESEND_RESPONSE" | jq .
    
    if echo "$RESEND_RESPONSE" | jq -e '.message' > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Solicitud enviada${NC}"
    else
        echo -e "${RED}✗ Error en la solicitud${NC}"
        exit 1
    fi
    
    echo ""
    echo -e "${YELLOW}⚠ Para obtener el token:${NC}"
    echo ""
    echo "  ${CYAN}Desde logs:${NC}"
    echo "  docker-compose logs api | grep 'RESEND VERIFICATION'"
    echo ""
    echo "  ${CYAN}Desde base de datos:${NC}"
    echo "  docker-compose exec db psql -U postgres -d siscom_db -c \\"
    echo "    \"SELECT token, expires_at FROM tokens_confirmacion \\"
    echo "    \"WHERE type='email_verification' AND used=false AND email='$EMAIL' \\"
    echo "    \"ORDER BY created_at DESC LIMIT 1;\""
    echo ""
    echo -e "${CYAN}Luego ejecuta:${NC}"
    echo "  $0 confirm-email <TOKEN_OBTENIDO>"
    echo ""
}

# ===========================================
# Comando: confirm-email
# ===========================================
confirm_email() {
    TOKEN="$1"
    
    if [ -z "$TOKEN" ]; then
        echo -e "${RED}Error: Falta el token${NC}"
        echo "Uso: $0 confirm-email <token>"
        exit 1
    fi
    
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  TEST: Confirmar Email${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    echo -e "${YELLOW}Token:${NC} $TOKEN"
    echo ""
    
    # Confirmar email
    echo -e "${CYAN}1. Confirmando email con token...${NC}"
    CONFIRM_RESPONSE=$(curl -s -X POST "$API_URL/auth/confirm-email" \
      -H "Content-Type: application/json" \
      -d "{\"token\": \"$TOKEN\"}")
    
    echo -e "${GREEN}Respuesta:${NC}"
    echo "$CONFIRM_RESPONSE" | jq .
    
    if echo "$CONFIRM_RESPONSE" | jq -e '.message' > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Email verificado exitosamente${NC}"
    else
        echo -e "${RED}✗ Error al verificar email${NC}"
        exit 1
    fi
    
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  ✓ Email verificado${NC}"
    echo -e "${GREEN}========================================${NC}"
}

# ===========================================
# Comando: full-verification-flow
# ===========================================
full_verification_flow() {
    EMAIL="$1"
    
    if [ -z "$EMAIL" ]; then
        echo -e "${RED}Error: Falta el email${NC}"
        echo "Uso: $0 full-verification-flow <email>"
        exit 1
    fi
    
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  TEST: Flujo Completo de Verificación${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    echo -e "${YELLOW}Email:${NC} $EMAIL"
    echo ""
    
    # 1. Reenviar verificación
    echo -e "${CYAN}1. Solicitando reenvío de verificación...${NC}"
    RESEND_RESPONSE=$(curl -s -X POST "$API_URL/auth/resend-verification" \
      -H "Content-Type: application/json" \
      -d "{\"email\": \"$EMAIL\"}")
    
    if echo "$RESEND_RESPONSE" | jq -e '.message' > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Solicitud enviada${NC}"
    else
        echo -e "${RED}✗ Error en la solicitud${NC}"
        exit 1
    fi
    
    echo ""
    
    # 2. Obtener token de la base de datos
    echo -e "${CYAN}2. Obteniendo token de la base de datos...${NC}"
    
    # Verificar si docker-compose está disponible
    if ! command -v docker-compose &> /dev/null; then
        echo -e "${RED}✗ docker-compose no está disponible${NC}"
        echo "Por favor, obtén el token manualmente:"
        echo "  docker-compose exec db psql -U postgres -d siscom_db -c \\"
        echo "    \"SELECT token FROM tokens_confirmacion \\"
        echo "    \"WHERE type='email_verification' AND used=false AND email='$EMAIL' \\"
        echo "    \"ORDER BY created_at DESC LIMIT 1;\""
        exit 1
    fi
    
    TOKEN=$(docker-compose exec -T db psql -U postgres -d siscom_db -t -c \
      "SELECT token FROM tokens_confirmacion WHERE type='email_verification' AND used=false AND email='$EMAIL' ORDER BY created_at DESC LIMIT 1;" 2>/dev/null | tr -d ' ' | tr -d '\n' | tr -d '\r')
    
    if [ -z "$TOKEN" ]; then
        echo -e "${RED}✗ No se pudo obtener el token de la BD${NC}"
        echo "Verifica que:"
        echo "  1. El usuario existe"
        echo "  2. El usuario no está verificado"
        echo "  3. Se generó un token en el paso anterior"
        exit 1
    fi
    
    echo -e "${GREEN}✓ Token obtenido: ${TOKEN:0:20}...${NC}"
    
    echo ""
    
    # 3. Confirmar email
    echo -e "${CYAN}3. Confirmando email con token...${NC}"
    CONFIRM_RESPONSE=$(curl -s -X POST "$API_URL/auth/confirm-email" \
      -H "Content-Type: application/json" \
      -d "{\"token\": \"$TOKEN\"}")
    
    if echo "$CONFIRM_RESPONSE" | jq -e '.message' > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Email verificado exitosamente${NC}"
        echo "$CONFIRM_RESPONSE" | jq .
    else
        echo -e "${RED}✗ Error al verificar email${NC}"
        echo "$CONFIRM_RESPONSE" | jq .
        exit 1
    fi
    
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  ✓ Flujo completado exitosamente${NC}"
    echo -e "${GREEN}========================================${NC}"
}

# ===========================================
# Main
# ===========================================

# Verificar que jq esté instalado
if ! command -v jq &> /dev/null; then
    echo -e "${RED}Error: jq no está instalado${NC}"
    echo "Instala jq con: sudo apt install jq"
    exit 1
fi

# Procesar comando
COMMAND="${1:-}"

case "$COMMAND" in
    change-password)
        shift
        change_password "$@"
        ;;
    resend-verification)
        shift
        resend_verification "$@"
        ;;
    confirm-email)
        shift
        confirm_email "$@"
        ;;
    full-verification-flow)
        shift
        full_verification_flow "$@"
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo -e "${RED}Error: Comando desconocido: $COMMAND${NC}"
        echo ""
        show_help
        exit 1
        ;;
esac

