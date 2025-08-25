from unittest.mock import MagicMock, patch

from src.secrets import (
    get_secret_json,
    get_secret_string,
    put_secret_json,
    put_secret_string,
)


@patch("boto3.client")
def test_get_secret_string(mock_client: MagicMock) -> None:
    mock = MagicMock()
    mock.get_secret_value.return_value = {"SecretString": "value"}
    mock_client.return_value = mock
    assert get_secret_string("name") == "value"


@patch("boto3.client")
def test_get_secret_json(mock_client: MagicMock) -> None:
    mock = MagicMock()
    mock.get_secret_value.return_value = {"SecretString": '{"a":1}'}
    mock_client.return_value = mock
    assert get_secret_json("name")["a"] == 1


@patch("boto3.client")
def test_put_secret_string(mock_client: MagicMock) -> None:
    mock = MagicMock()
    mock.describe_secret.side_effect = [None]
    mock_client.return_value = mock
    put_secret_string("n", "v")
    assert mock.put_secret_value.called or mock.create_secret.called


@patch("boto3.client")
def test_put_secret_json(mock_client: MagicMock) -> None:
    mock = MagicMock()
    mock.describe_secret.side_effect = [None]
    mock_client.return_value = mock
    put_secret_json("n", {"a": 1})
    assert mock.put_secret_value.called or mock.create_secret.called
