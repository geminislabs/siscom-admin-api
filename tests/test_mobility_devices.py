from uuid import uuid4

from fastapi import status

from app.models.mobility_device import MobilityDevice
from app.models.user import User
from app.models.user_device import UserDevice


def test_register_mobility_device_success(authenticated_client):
    payload = {
        "device_type": "PHONE",
        "platform": "android",
        "device_name": "Pixel 8",
        "external_device_id": "android-id-123",
        "app_version": "1.9.0",
        "os_version": "Android 15",
        "metadata": {"manufacturer": "Google"},
    }

    response = authenticated_client.post("/api/v1/mobility/devices", json=payload)
    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()
    assert data["device_type"] == "PHONE"
    assert data["platform"] == "android"
    assert data["device_name"] == "Pixel 8"
    assert data["is_active"] is True
    assert data["metadata"]["manufacturer"] == "Google"
    assert data["id"] is not None
    assert data["user_id"] is not None
    assert data["created_at"] is not None
    assert data["updated_at"] is not None


def test_register_mobility_device_rejects_notification_device_from_other_user(
    authenticated_client, db_session, test_organization_data
):
    other_user = User(
        id=uuid4(),
        organization_id=test_organization_data.id,
        cognito_sub="other-cognito-sub",
        email="other@example.com",
        full_name="Other User",
        is_master=False,
    )
    db_session.add(other_user)
    db_session.flush()

    foreign_notification_device = UserDevice(
        id=uuid4(),
        user_id=other_user.id,
        device_token="token-other-user",
        platform="ios",
        endpoint_arn="arn:aws:sns:us-east-1:123456789012:endpoint/APNS/app/abc",
        is_active=True,
    )
    db_session.add(foreign_notification_device)
    db_session.commit()

    payload = {
        "device_type": "WATCH",
        "platform": "ios",
        "notification_device_id": str(foreign_notification_device.id),
    }

    response = authenticated_client.post("/api/v1/mobility/devices", json=payload)
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "notification_device_id" in response.json()["detail"]


def test_register_mobility_device_rejects_duplicate_notification_device_id(
    authenticated_client, db_session, test_user_data
):
    notification_device = UserDevice(
        id=uuid4(),
        user_id=test_user_data.id,
        device_token="token-shared-notification",
        platform="android",
        endpoint_arn="arn:aws:sns:us-east-1:123456789012:endpoint/GCM/app/xyz",
        is_active=True,
    )
    db_session.add(notification_device)
    db_session.flush()

    first = MobilityDevice(
        user_id=test_user_data.id,
        device_type="PHONE",
        platform="android",
        notification_device_id=notification_device.id,
        mobility_metadata={},
    )
    db_session.add(first)
    db_session.commit()

    payload = {
        "device_type": "WEARABLE",
        "platform": "android",
        "notification_device_id": str(notification_device.id),
    }

    response = authenticated_client.post("/api/v1/mobility/devices", json=payload)
    assert response.status_code == status.HTTP_409_CONFLICT
    assert "No fue posible registrar" in response.json()["detail"]


def test_register_mobility_device_invalid_device_type(authenticated_client):
    payload = {
        "device_type": "TABLET",
        "platform": "android",
    }

    response = authenticated_client.post("/api/v1/mobility/devices", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_list_mobility_devices_returns_only_current_user_records(
    authenticated_client, db_session, test_user_data, test_organization_data
):
    own_device = MobilityDevice(
        user_id=test_user_data.id,
        device_type="PHONE",
        platform="android",
        is_active=True,
        mobility_metadata={"kind": "own"},
    )

    other_user = User(
        id=uuid4(),
        organization_id=test_organization_data.id,
        cognito_sub="other-cognito-list",
        email="other-list@example.com",
        full_name="Other List User",
        is_master=False,
    )
    db_session.add(other_user)
    db_session.flush()

    foreign_device = MobilityDevice(
        user_id=other_user.id,
        device_type="WATCH",
        platform="ios",
        is_active=True,
        mobility_metadata={"kind": "foreign"},
    )

    db_session.add(own_device)
    db_session.add(foreign_device)
    db_session.commit()

    response = authenticated_client.get("/api/v1/mobility/devices")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 1
    assert data[0]["user_id"] == str(test_user_data.id)
    assert data[0]["metadata"]["kind"] == "own"


def test_list_mobility_devices_supports_filters(
    authenticated_client, db_session, test_user_data
):
    active_phone = MobilityDevice(
        user_id=test_user_data.id,
        device_type="PHONE",
        platform="android",
        is_active=True,
        mobility_metadata={},
    )
    inactive_watch = MobilityDevice(
        user_id=test_user_data.id,
        device_type="WATCH",
        platform="ios",
        is_active=False,
        mobility_metadata={},
    )

    db_session.add(active_phone)
    db_session.add(inactive_watch)
    db_session.commit()

    response = authenticated_client.get(
        "/api/v1/mobility/devices?is_active=false&device_type=WATCH"
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 1
    assert data[0]["device_type"] == "WATCH"
    assert data[0]["is_active"] is False
