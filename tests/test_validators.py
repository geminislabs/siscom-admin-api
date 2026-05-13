import pytest

from app.utils.validators import (
    sanitize_contact_field,
    sanitize_html,
    validate_name,
    validate_password,
    validate_phone,
)


def test_validate_password_accepts_secure_password():
    password = "Password1!"
    assert validate_password(password) == password


def test_validate_password_rejects_too_short():
    with pytest.raises(ValueError) as exc_info:
        validate_password("Aa1!")
    assert "al menos 8 caracteres" in str(exc_info.value)


def test_validate_password_rejects_too_long():
    with pytest.raises(ValueError) as exc_info:
        validate_password("A1!" + ("x" * 70))
    assert "más de 72 caracteres" in str(exc_info.value)


def test_validate_password_requires_uppercase():
    with pytest.raises(ValueError) as exc_info:
        validate_password("password1!")
    assert "letra mayúscula" in str(exc_info.value)


def test_validate_password_requires_number():
    with pytest.raises(ValueError) as exc_info:
        validate_password("Password!")
    assert "al menos un número" in str(exc_info.value)


def test_validate_password_requires_special_character():
    with pytest.raises(ValueError) as exc_info:
        validate_password("Password1")
    assert "carácter especial" in str(exc_info.value)


def test_validate_name_strips_whitespace():
    assert validate_name("  Juan Perez  ") == "Juan Perez"


def test_validate_name_rejects_empty_value():
    with pytest.raises(ValueError) as exc_info:
        validate_name("   ")
    assert "no puede estar vacío" in str(exc_info.value)


def test_validate_name_rejects_single_character():
    with pytest.raises(ValueError) as exc_info:
        validate_name("A")
    assert "al menos 2 caracteres" in str(exc_info.value)


def test_sanitize_html_returns_empty_input_as_is():
    assert sanitize_html("") == ""


def test_sanitize_html_strips_and_escapes_markup():
    raw = "  <script>alert('x')</script>  "
    assert sanitize_html(raw) == "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;"


def test_sanitize_html_rejects_when_text_exceeds_limit():
    with pytest.raises(ValueError) as exc_info:
        sanitize_html("hola", max_length=3)
    assert "no puede exceder 3 caracteres" in str(exc_info.value)


def test_sanitize_contact_field_returns_empty_input_as_is():
    assert sanitize_contact_field("", field_name="mensaje") == ""


def test_sanitize_contact_field_rejects_blank_after_strip():
    with pytest.raises(ValueError) as exc_info:
        sanitize_contact_field("   ", field_name="nombre")
    assert "El campo nombre no puede estar vacío" in str(exc_info.value)


def test_sanitize_contact_field_rejects_when_exceeds_limit():
    with pytest.raises(ValueError) as exc_info:
        sanitize_contact_field("abcdef", field_name="asunto", max_length=5)
    assert "El campo asunto no puede exceder 5 caracteres" in str(exc_info.value)


def test_sanitize_contact_field_escapes_html_content():
    value = " <b>Consulta urgente</b> "
    assert sanitize_contact_field(value, field_name="mensaje") == (
        "&lt;b&gt;Consulta urgente&lt;/b&gt;"
    )


def test_validate_phone_returns_empty_input_as_is():
    assert validate_phone("") == ""


def test_validate_phone_accepts_common_formats():
    phone = "+52 (55) 1234-5678"
    assert validate_phone(phone) == "+52 (55) 1234-5678"


def test_validate_phone_rejects_invalid_characters():
    with pytest.raises(ValueError) as exc_info:
        validate_phone("555-ABCD-123")
    assert "solo puede contener números" in str(exc_info.value)


def test_validate_phone_requires_minimum_digits():
    with pytest.raises(ValueError) as exc_info:
        validate_phone("12-34")
    assert "al menos 7 dígitos" in str(exc_info.value)


def test_validate_phone_rejects_more_than_20_digits():
    with pytest.raises(ValueError) as exc_info:
        validate_phone("+123456789012345678901")
    assert "más de 20 dígitos" in str(exc_info.value)


def test_validate_phone_strips_whitespace_before_validating():
    assert validate_phone("   +52 5512345678   ") == "+52 5512345678"
