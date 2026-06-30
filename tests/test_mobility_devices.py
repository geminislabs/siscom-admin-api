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


def test_register_mobility_device_upsert_by_notification_device_id(
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
        "device_name": "Wearable Update",
        "notification_device_id": str(notification_device.id),
    }

    response = authenticated_client.post("/api/v1/mobility/devices", json=payload)
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["id"] == str(first.id)
    assert data["device_type"] == "WEARABLE"
    assert data["device_name"] == "Wearable Update"


def test_register_mobility_device_upsert_by_external_device_id(
    authenticated_client, db_session, test_user_data
):
    original = MobilityDevice(
        user_id=test_user_data.id,
        device_type="PHONE",
        platform="android",
        external_device_id="android-id-upsert",
        app_version="1.0.0",
        mobility_metadata={"manufacturer": "Google"},
    )
    db_session.add(original)
    db_session.commit()
    db_session.refresh(original)

    payload = {
        "device_type": "PHONE",
        "platform": "android",
        "external_device_id": "android-id-upsert",
        "app_version": "2.0.0",
        "metadata": {"manufacturer": "Google", "updated": True},
    }

    response = authenticated_client.post("/api/v1/mobility/devices", json=payload)
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["id"] == str(original.id)
    assert data["app_version"] == "2.0.0"
    assert data["metadata"]["updated"] is True


def test_register_mobility_device_upsert_conflict_on_notification_device_id(
    authenticated_client, db_session, test_user_data
):
    notification_device = UserDevice(
        id=uuid4(),
        user_id=test_user_data.id,
        device_token="token-conflict",
        platform="android",
        endpoint_arn="arn:aws:sns:us-east-1:123456789012:endpoint/GCM/app/xyz2",
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
    second = MobilityDevice(
        user_id=test_user_data.id,
        device_type="WATCH",
        platform="android",
        external_device_id="external-conflict",
        mobility_metadata={},
    )
    db_session.add(first)
    db_session.add(second)
    db_session.commit()

    payload = {
        "device_type": "WATCH",
        "platform": "android",
        "external_device_id": "external-conflict",
        "notification_device_id": str(notification_device.id),
    }

    response = authenticated_client.post("/api/v1/mobility/devices", json=payload)
    assert response.status_code == status.HTTP_409_CONFLICT
    assert "registrar/actualizar" in response.json()["detail"]


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


def test_get_mobility_device_detail_success(
    authenticated_client, db_session, test_user_data
):
    device = MobilityDevice(
        user_id=test_user_data.id,
        device_type="PHONE",
        platform="ios",
        device_name="iPhone 16",
        app_version="3.0.0",
        is_active=True,
        mobility_metadata={"color": "black"},
    )
    db_session.add(device)
    db_session.commit()
    db_session.refresh(device)

    response = authenticated_client.get(f"/api/v1/mobility/devices/{device.id}")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()["data"]
    assert data["id"] == str(device.id)
    assert data["device_type"] == "PHONE"
    assert data["device_name"] == "iPhone 16"
    assert data["app_version"] == "3.0.0"
    assert data["metadata"]["color"] == "black"


def test_get_mobility_device_not_found(authenticated_client):
    fake_id = uuid4()
    response = authenticated_client.get(f"/api/v1/mobility/devices/{fake_id}")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "no encontrado" in response.json()["detail"].lower()


def test_get_mobility_device_forbidden_other_user(
    authenticated_client, db_session, test_organization_data
):
    other_user = User(
        id=uuid4(),
        organization_id=test_organization_data.id,
        cognito_sub="other-forbidden",
        email="other-forbidden@example.com",
        full_name="Forbidden User",
        is_master=False,
    )
    db_session.add(other_user)
    db_session.flush()

    other_device = MobilityDevice(
        user_id=other_user.id,
        device_type="WATCH",
        platform="android",
        is_active=True,
        mobility_metadata={},
    )
    db_session.add(other_device)
    db_session.commit()

    response = authenticated_client.get(f"/api/v1/mobility/devices/{other_device.id}")
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "permiso" in response.json()["detail"].lower()


def test_update_mobility_device_success(
    authenticated_client, db_session, test_user_data
):
    device = MobilityDevice(
        user_id=test_user_data.id,
        device_type="PHONE",
        platform="android",
        device_name="Pixel 9",
        app_version="1.0.0",
        os_version="Android 15",
        is_active=True,
        mobility_metadata={"initial": True},
    )
    db_session.add(device)
    db_session.commit()
    db_session.refresh(device)

    payload = {
        "device_name": "Pixel 9 Pro",
        "app_version": "1.1.0",
        "os_version": "Android 15.1",
        "metadata": {"initial": False, "updated": True},
    }

    response = authenticated_client.patch(
        f"/api/v1/mobility/devices/{device.id}", json=payload
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()["data"]
    assert data["id"] == str(device.id)
    assert data["device_name"] == "Pixel 9 Pro"
    assert data["app_version"] == "1.1.0"
    assert data["os_version"] == "Android 15.1"
    assert data["metadata"]["updated"] is True
    assert data["metadata"]["initial"] is False


def test_update_mobility_device_partial_fields(
    authenticated_client, db_session, test_user_data
):
    device = MobilityDevice(
        user_id=test_user_data.id,
        device_type="WATCH",
        platform="ios",
        device_name="Apple Watch",
        app_version="5.0.0",
        is_active=True,
        mobility_metadata={"original": True},
    )
    db_session.add(device)
    db_session.commit()
    db_session.refresh(device)

    payload = {"device_name": "Apple Watch Series 10"}

    response = authenticated_client.patch(
        f"/api/v1/mobility/devices/{device.id}", json=payload
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()["data"]
    assert data["device_name"] == "Apple Watch Series 10"
    assert data["app_version"] == "5.0.0"
    assert data["metadata"]["original"] is True


def test_activate_mobility_device_success(
    authenticated_client, db_session, test_user_data
):
    device = MobilityDevice(
        user_id=test_user_data.id,
        device_type="PHONE",
        platform="android",
        is_active=False,
        mobility_metadata={},
    )
    db_session.add(device)
    db_session.commit()
    db_session.refresh(device)

    response = authenticated_client.post(
        f"/api/v1/mobility/devices/{device.id}/activate"
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()["data"]
    assert data["id"] == str(device.id)
    assert data["is_active"] is True


def test_deactivate_mobility_device_success(
    authenticated_client, db_session, test_user_data
):
    device = MobilityDevice(
        user_id=test_user_data.id,
        device_type="WATCH",
        platform="ios",
        is_active=True,
        mobility_metadata={},
    )
    db_session.add(device)
    db_session.commit()
    db_session.refresh(device)

    response = authenticated_client.post(
        f"/api/v1/mobility/devices/{device.id}/deactivate"
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()["data"]
    assert data["id"] == str(device.id)
    assert data["is_active"] is False


def test_associate_notification_device_success(
    authenticated_client, db_session, test_user_data
):
    notification_device = UserDevice(
        id=uuid4(),
        user_id=test_user_data.id,
        device_token="token-associate-success",
        platform="ios",
        endpoint_arn="arn:aws:sns:us-east-1:123456789012:endpoint/APNS/app/abc123",
        is_active=True,
    )
    db_session.add(notification_device)
    db_session.flush()

    mobility_device = MobilityDevice(
        user_id=test_user_data.id,
        device_type="PHONE",
        platform="ios",
        is_active=True,
        mobility_metadata={},
    )
    db_session.add(mobility_device)
    db_session.commit()
    db_session.refresh(mobility_device)

    payload = {"notification_device_id": str(notification_device.id)}

    response = authenticated_client.put(
        f"/api/v1/mobility/devices/{mobility_device.id}/notification-device",
        json=payload,
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()["data"]
    assert data["id"] == str(mobility_device.id)
    assert data["notification_device_id"] == str(notification_device.id)


def test_associate_notification_device_not_found(
    authenticated_client, db_session, test_user_data
):
    mobility_device = MobilityDevice(
        user_id=test_user_data.id,
        device_type="PHONE",
        platform="ios",
        is_active=True,
        mobility_metadata={},
    )
    db_session.add(mobility_device)
    db_session.commit()
    db_session.refresh(mobility_device)

    fake_notification_id = uuid4()
    payload = {"notification_device_id": str(fake_notification_id)}

    response = authenticated_client.put(
        f"/api/v1/mobility/devices/{mobility_device.id}/notification-device",
        json=payload,
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "notification_device_id" in response.json()["detail"]


def test_associate_notification_device_from_other_user(
    authenticated_client, db_session, test_user_data, test_organization_data
):
    other_user = User(
        id=uuid4(),
        organization_id=test_organization_data.id,
        cognito_sub="other-notification-owner",
        email="other-notification@example.com",
        full_name="Other Notification User",
        is_master=False,
    )
    db_session.add(other_user)
    db_session.flush()

    other_notification = UserDevice(
        id=uuid4(),
        user_id=other_user.id,
        device_token="token-other-owner",
        platform="android",
        endpoint_arn="arn:aws:sns:us-east-1:123456789012:endpoint/GCM/app/xyz789",
        is_active=True,
    )
    db_session.add(other_notification)
    db_session.flush()

    mobility_device = MobilityDevice(
        user_id=test_user_data.id,
        device_type="WATCH",
        platform="android",
        is_active=True,
        mobility_metadata={},
    )
    db_session.add(mobility_device)
    db_session.commit()
    db_session.refresh(mobility_device)

    payload = {"notification_device_id": str(other_notification.id)}

    response = authenticated_client.put(
        f"/api/v1/mobility/devices/{mobility_device.id}/notification-device",
        json=payload,
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "notification_device_id" in response.json()["detail"]


def test_associate_notification_device_already_used_by_another(
    authenticated_client, db_session, test_user_data
):
    notification_device = UserDevice(
        id=uuid4(),
        user_id=test_user_data.id,
        device_token="token-already-used",
        platform="ios",
        endpoint_arn="arn:aws:sns:us-east-1:123456789012:endpoint/APNS/app/xyz",
        is_active=True,
    )
    db_session.add(notification_device)
    db_session.flush()

    first_mobility = MobilityDevice(
        user_id=test_user_data.id,
        device_type="PHONE",
        platform="ios",
        notification_device_id=notification_device.id,
        is_active=True,
        mobility_metadata={},
    )
    second_mobility = MobilityDevice(
        user_id=test_user_data.id,
        device_type="WATCH",
        platform="ios",
        is_active=True,
        mobility_metadata={},
    )
    db_session.add(first_mobility)
    db_session.add(second_mobility)
    db_session.commit()
    db_session.refresh(second_mobility)

    payload = {"notification_device_id": str(notification_device.id)}

    response = authenticated_client.put(
        f"/api/v1/mobility/devices/{second_mobility.id}/notification-device",
        json=payload,
    )
    assert response.status_code == status.HTTP_409_CONFLICT
    assert "asociado" in response.json()["detail"]


def test_dissociate_notification_device_success(
    authenticated_client, db_session, test_user_data
):
    notification_device = UserDevice(
        id=uuid4(),
        user_id=test_user_data.id,
        device_token="token-dissociate",
        platform="android",
        endpoint_arn="arn:aws:sns:us-east-1:123456789012:endpoint/GCM/app/abc",
        is_active=True,
    )
    db_session.add(notification_device)
    db_session.flush()

    mobility_device = MobilityDevice(
        user_id=test_user_data.id,
        device_type="PHONE",
        platform="android",
        notification_device_id=notification_device.id,
        is_active=True,
        mobility_metadata={},
    )
    db_session.add(mobility_device)
    db_session.commit()
    db_session.refresh(mobility_device)

    response = authenticated_client.delete(
        f"/api/v1/mobility/devices/{mobility_device.id}/notification-device"
    )
    assert response.status_code == status.HTTP_204_NO_CONTENT

    db_session.refresh(mobility_device)
    assert mobility_device.notification_device_id is None


def test_dissociate_notification_device_when_already_none(
    authenticated_client, db_session, test_user_data
):
    mobility_device = MobilityDevice(
        user_id=test_user_data.id,
        device_type="WATCH",
        platform="ios",
        notification_device_id=None,
        is_active=True,
        mobility_metadata={},
    )
    db_session.add(mobility_device)
    db_session.commit()
    db_session.refresh(mobility_device)

    response = authenticated_client.delete(
        f"/api/v1/mobility/devices/{mobility_device.id}/notification-device"
    )
    assert response.status_code == status.HTTP_204_NO_CONTENT
