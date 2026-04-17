import json
import logging
import sys
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """
    Formatter que convierte los logs a formato JSON para mejor parsing.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Agregar información de excepción si existe
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Agregar datos extras si existen
        if hasattr(record, "extra_data"):
            log_data["extra"] = record.extra_data

        return json.dumps(log_data, ensure_ascii=False)


class HealthCheckFilter(logging.Filter):
    """Suprime los logs de acceso del endpoint /health cuando son exitosos (2xx)."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Formato preferente de uvicorn.access:
        # args = (client_addr, method, path_qs, http_version, status_code)
        if record.name == "uvicorn.access" and isinstance(record.args, tuple):
            if len(record.args) >= 3:
                path = str(record.args[2]).split("?", 1)[0]
                if path == "/health":
                    return False

        # Fallback para otros formatters que serializan solo el mensaje
        message = record.getMessage()
        if " /health" in message and "HTTP/" in message:
            return False

        return True


def setup_logging(level: str = "INFO") -> None:
    """
    Configura el sistema de logging con formato JSON.

    Args:
        level: Nivel de logging (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Configurar logger raíz
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remover handlers existentes
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Crear handler para stdout
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root_logger.addHandler(handler)

    # Configurar loggers específicos
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.setLevel(logging.INFO)
    health_filter = HealthCheckFilter()
    uvicorn_access.addFilter(health_filter)
    for handler in uvicorn_access.handlers:
        handler.addFilter(health_filter)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Obtiene un logger con el nombre especificado.

    Args:
        name: Nombre del logger (generalmente __name__)

    Returns:
        Logger configurado
    """
    return logging.getLogger(name)
