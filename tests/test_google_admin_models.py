import pytest
from pydantic import ValidationError

from google_mcp.google_admin.models import AddRoleRequest, RemoveRoleRequest


def test_add_role_request_valid():
    req = AddRoleRequest(
        user_key="user@example.com",
        admin_role="arn:aws:iam::123456789012:role/Admin",
        identity_provider="arn:aws:iam::123456789012:saml-provider/GoogleIdP",
    )
    assert req.admin_role.endswith(":role/Admin")


def test_add_role_request_invalid_missing_fields():
    with pytest.raises(ValidationError):
        AddRoleRequest(
            user_key="user@example.com",
            admin_role="arn:aws:iam::123456789012:role/Admin",
            identity_provider="",  # invalid pattern
        )


@pytest.mark.parametrize(
    "field,value",
    [
        (
            "admin_role",
            "arn:aws:iam::123:role/Admin",
        ),  # too short account digits
        (
            "admin_role",
            "arn:aws:iam::123456789012:role/Invalid Space",
        ),  # space
        (
            "identity_provider",
            "arn:aws:iam::123456789012:saml-provider/Invalid*",
        ),  # invalid char
        (
            "identity_provider",
            "arn:aws:iam::123:saml-provider/GoogleIdP",
        ),  # short
    ],
)
def test_add_role_request_invalid_arn_formats(field, value):
    data = {
        "user_key": "user@example.com",
        "admin_role": "arn:aws:iam::123456789012:role/Admin",
        "identity_provider": "arn:aws:iam::123456789012:saml-provider/GoogleIdP",
    }
    data[field] = value
    with pytest.raises(ValidationError):
        AddRoleRequest(**data)


def test_remove_role_request_valid():
    req = RemoveRoleRequest(
        user_key="user@example.com",
        admin_role="arn:aws:iam::123456789012:role/DevRole",
        identity_provider="arn:aws:iam::123456789012:saml-provider/GoogleIdP",
    )
    assert req.identity_provider.endswith("saml-provider/GoogleIdP")
