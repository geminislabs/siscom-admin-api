import logging
import re

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)

_sns_client = None


def get_sns_client():
    global _sns_client
    if _sns_client is None:
        client_kwargs = {"region_name": settings.AWS_REGION}

        # Si hay credenciales explícitas (local), se usan.
        # Si no hay, boto3 usa su cadena por defecto (IAM Role en producción).
        if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
            client_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
            client_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY

        _sns_client = boto3.client("sns", **client_kwargs)
    return _sns_client


def _platform_application_arn(platform: str) -> str:
    if platform == "ios":
        arn = settings.SNS_PLATFORM_APPLICATION_ARN_IOS
    elif platform == "android":
        arn = settings.SNS_PLATFORM_APPLICATION_ARN_ANDROID
    else:
        raise ValueError("Invalid platform")

    if not arn:
        raise ValueError(f"SNS platform ARN no configurado para plataforma: {platform}")

    return arn


def _extract_arn_from_error(message: str) -> str | None:
    match = re.search(r"(arn:aws:sns:[A-Za-z0-9:_/-]+)", message)
    if match:
        return match.group(1)
    return None


def create_endpoint(device_token: str, platform: str) -> str:
    sns = get_sns_client()
    platform_arn = _platform_application_arn(platform)

    try:
        response = sns.create_platform_endpoint(
            PlatformApplicationArn=platform_arn,
            Token=device_token,
        )
        return response["EndpointArn"]
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        message = exc.response.get("Error", {}).get("Message", "")

        if code == "InvalidParameter" and "already exists" in message.lower():
            existing_arn = _extract_arn_from_error(message)
            if existing_arn:
                logger.info(
                    "SNS endpoint duplicado detectado para token; reutilizando ARN: %s",
                    existing_arn,
                )
                return existing_arn
        raise


def endpoint_is_valid(endpoint_arn: str) -> bool:
    sns = get_sns_client()
    try:
        response = sns.get_endpoint_attributes(EndpointArn=endpoint_arn)
        enabled = response.get("Attributes", {}).get("Enabled", "false")
        return str(enabled).lower() == "true"
    except ClientError:
        return False


def get_or_recreate_endpoint(
    device_token: str,
    platform: str,
    endpoint_arn: str | None,
) -> tuple[str, bool]:
    if endpoint_arn and endpoint_is_valid(endpoint_arn):
        return endpoint_arn, False
    return create_endpoint(device_token=device_token, platform=platform), True
