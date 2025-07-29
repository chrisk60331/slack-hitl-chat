"""
Unit tests for the CLI interface.

Tests the command-line interface for the HITL MCP server.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from src.cli import cli, _expand_env_vars, _load_config_from_file, _validate_config
from src.mcp_server import ApprovalConfig


class TestCLI:
    """Test cases for the CLI commands."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_cli_help(self) -> None:
        """Test CLI help command."""
        result = self.runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "AgentCore Human-in-the-Loop MCP Server CLI" in result.output

    @patch('src.cli._run_server')
    def test_serve_command_with_args(self, mock_run_server: Mock) -> None:
        """Test serve command with command-line arguments."""
        result = self.runner.invoke(cli, [
            "serve",
            "--lambda-url", "https://test.lambda-url.aws.com",
            "--approver", "security_team",
            "--timeout", "3600",
            "--no-auto-approve-low-risk"
        ])
        
        assert result.exit_code == 0
        assert "Starting HITL MCP server..." in result.output
        assert "Lambda URL: https://test.lambda-url.aws.com" in result.output
        assert "Default approver: security_team" in result.output
        assert "Timeout: 3600s" in result.output
        assert "Auto-approve low risk: False" in result.output
        mock_run_server.assert_called_once()

    @patch('src.cli._run_server')
    def test_serve_command_with_env_vars(self, mock_run_server: Mock) -> None:
        """Test serve command with environment variables."""
        env_vars = {
            "LAMBDA_FUNCTION_URL": "https://env.lambda-url.aws.com",
            "DEFAULT_APPROVER": "env_admin",
            "APPROVAL_TIMEOUT": "7200",
            "AUTO_APPROVE_LOW_RISK": "false"
        }
        
        result = self.runner.invoke(cli, ["serve"], env=env_vars)
        
        assert result.exit_code == 0
        assert "Lambda URL: https://env.lambda-url.aws.com" in result.output
        assert "Default approver: env_admin" in result.output
        assert "Timeout: 7200s" in result.output
        mock_run_server.assert_called_once()

    def test_serve_command_missing_lambda_url(self) -> None:
        """Test serve command without required Lambda URL."""
        result = self.runner.invoke(cli, ["serve"])
        
        assert result.exit_code == 2  # Click error code for missing required option
        assert "Missing option" in result.output

    @patch('src.cli._load_config_from_file')
    @patch('src.cli._run_server')
    def test_serve_command_with_config_file(
        self, 
        mock_run_server: Mock, 
        mock_load_config: Mock
    ) -> None:
        """Test serve command with configuration file."""
        mock_config = ApprovalConfig(
            lambda_function_url="https://config.lambda-url.aws.com",
            default_approver="config_admin"
        )
        mock_load_config.return_value = mock_config
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config_file = f.name
            json.dump({"lambda_function_url": "https://config.lambda-url.aws.com"}, f)
        
        try:
            result = self.runner.invoke(cli, [
                "serve",
                "--config-file", config_file
            ])
            
            assert result.exit_code == 0
            assert "Lambda URL: https://config.lambda-url.aws.com" in result.output
            mock_load_config.assert_called_once_with(config_file)
            mock_run_server.assert_called_once()
        finally:
            Path(config_file).unlink()

    @patch('src.cli._validate_config')
    def test_serve_command_validation_error(self, mock_validate: Mock) -> None:
        """Test serve command with validation error."""
        mock_validate.side_effect = ValidationError.from_exception_data(
            "Test", 
            [{"type": "missing", "loc": ("lambda_function_url",), "msg": "Field required"}]
        )
        
        result = self.runner.invoke(cli, [
            "serve",
            "--lambda-url", "invalid-url"
        ])
        
        assert result.exit_code == 1
        assert "Configuration error" in result.output

    def test_generate_config_command(self) -> None:
        """Test generate-config command."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "test-config.json"
            
            result = self.runner.invoke(cli, [
                "generate-config",
                "--output", str(output_file),
                "--lambda-url", "https://test.lambda-url.aws.com",
                "--table-name", "test-table",
                "--sns-topic-arn", "arn:aws:sns:us-east-1:123456789012:test-topic",
                "--aws-region", "us-west-2"
            ])
            
            assert result.exit_code == 0
            assert "MCP configuration written to" in result.output
            
            # Verify config file content
            assert output_file.exists()
            with output_file.open() as f:
                config = json.load(f)
            
            assert "mcpServers" in config
            assert "hitl-approval" in config["mcpServers"]
            server_config = config["mcpServers"]["hitl-approval"]
            assert server_config["env"]["LAMBDA_FUNCTION_URL"] == "https://test.lambda-url.aws.com"
            assert server_config["env"]["TABLE_NAME"] == "test-table"
            assert server_config["env"]["SNS_TOPIC_ARN"] == "arn:aws:sns:us-east-1:123456789012:test-topic"
            assert server_config["env"]["AWS_REGION"] == "us-west-2"

    def test_generate_config_minimal(self) -> None:
        """Test generate-config command with minimal options."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "minimal-config.json"
            
            result = self.runner.invoke(cli, [
                "generate-config",
                "--output", str(output_file),
                "--lambda-url", "https://minimal.lambda-url.aws.com"
            ])
            
            assert result.exit_code == 0
            
            # Verify config file content
            with output_file.open() as f:
                config = json.load(f)
            
            server_config = config["mcpServers"]["hitl-approval"]
            assert server_config["env"]["LAMBDA_FUNCTION_URL"] == "https://minimal.lambda-url.aws.com"
            assert "TABLE_NAME" not in server_config["env"]
            assert "SNS_TOPIC_ARN" not in server_config["env"]

    @patch('httpx.Client')
    def test_check_approval_command_success(self, mock_client_class: Mock) -> None:
        """Test check-approval command with successful response."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.json.return_value = {
            "status": "approve",
            "timestamp": "2024-01-01T00:00:00Z",
            "approver": "admin"
        }
        mock_response.raise_for_status.return_value = None
        mock_client.get.return_value = mock_response
        mock_client_class.return_value.__enter__.return_value = mock_client
        
        result = self.runner.invoke(cli, [
            "check-approval",
            "--lambda-url", "https://test.lambda-url.aws.com",
            "--request-id", "test-123"
        ])
        
        assert result.exit_code == 0
        assert "✅ Request test-123: approve" in result.output
        assert "Timestamp: 2024-01-01T00:00:00Z" in result.output
        assert "Approver: admin" in result.output

    @patch('httpx.Client')
    def test_check_approval_command_pending(self, mock_client_class: Mock) -> None:
        """Test check-approval command with pending status."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.json.return_value = {
            "status": "pending",
            "timestamp": "2024-01-01T00:00:00Z"
        }
        mock_response.raise_for_status.return_value = None
        mock_client.get.return_value = mock_response
        mock_client_class.return_value.__enter__.return_value = mock_client
        
        result = self.runner.invoke(cli, [
            "check-approval",
            "--lambda-url", "https://test.lambda-url.aws.com",
            "--request-id", "test-pending"
        ])
        
        assert result.exit_code == 0
        assert "⏳ Request test-pending: pending" in result.output

    @patch('httpx.Client')
    def test_check_approval_command_http_error(self, mock_client_class: Mock) -> None:
        """Test check-approval command with HTTP error."""
        mock_client = Mock()
        mock_client.get.side_effect = Exception("Connection error")
        mock_client_class.return_value.__enter__.return_value = mock_client
        
        result = self.runner.invoke(cli, [
            "check-approval",
            "--lambda-url", "https://test.lambda-url.aws.com",
            "--request-id", "test-error"
        ])
        
        assert result.exit_code == 1
        assert "Error checking approval" in result.output

    def test_init_config_command(self) -> None:
        """Test init-config command."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "init-config.json"
            
            result = self.runner.invoke(cli, [
                "init-config",
                "--output", str(output_file)
            ])
            
            assert result.exit_code == 0
            assert "Configuration template written to" in result.output
            
            # Verify config file content
            assert output_file.exists()
            with output_file.open() as f:
                config = json.load(f)
            
            assert config["lambda_function_url"] == "${LAMBDA_FUNCTION_URL}"
            assert config["default_approver"] == "admin"
            assert config["timeout_seconds"] == 1800
            assert config["auto_approve_low_risk"] is True
            assert "required_approvers" in config


class TestConfigHelpers:
    """Test cases for configuration helper functions."""

    def test_expand_env_vars_simple(self) -> None:
        """Test expanding simple environment variables."""
        import os
        
        os.environ["TEST_VAR"] = "test_value"
        try:
            data = {"key": "${TEST_VAR}"}
            result = _expand_env_vars(data)
            assert result["key"] == "test_value"
        finally:
            del os.environ["TEST_VAR"]

    def test_expand_env_vars_with_default(self) -> None:
        """Test expanding environment variables with default values."""
        data = {"key": "${NONEXISTENT_VAR:-default_value}"}
        result = _expand_env_vars(data)
        assert result["key"] == "default_value"

    def test_expand_env_vars_nested(self) -> None:
        """Test expanding environment variables in nested structures."""
        import os
        
        os.environ["NESTED_VAR"] = "nested_value"
        try:
            data = {
                "level1": {
                    "level2": ["${NESTED_VAR}", "static"],
                    "other": "${NONEXISTENT:-fallback}"
                }
            }
            result = _expand_env_vars(data)
            assert result["level1"]["level2"][0] == "nested_value"
            assert result["level1"]["level2"][1] == "static"
            assert result["level1"]["other"] == "fallback"
        finally:
            del os.environ["NESTED_VAR"]

    def test_expand_env_vars_no_expansion(self) -> None:
        """Test that non-variable strings are not expanded."""
        data = {
            "normal_string": "just a string",
            "number": 42,
            "boolean": True,
            "null": None
        }
        result = _expand_env_vars(data)
        assert result == data

    def test_load_config_from_file_success(self) -> None:
        """Test successful config loading from file."""
        config_data = {
            "lambda_function_url": "https://test.lambda-url.aws.com",
            "default_approver": "test_admin",
            "timeout_seconds": 3600
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config_file = f.name
            json.dump(config_data, f)
        
        try:
            config = _load_config_from_file(config_file)
            assert isinstance(config, ApprovalConfig)
            assert config.lambda_function_url == "https://test.lambda-url.aws.com"
            assert config.default_approver == "test_admin"
            assert config.timeout_seconds == 3600
        finally:
            Path(config_file).unlink()

    def test_load_config_from_file_not_found(self) -> None:
        """Test config loading when file doesn't exist."""
        with pytest.raises(Exception):  # Should raise ClickException
            _load_config_from_file("/nonexistent/path.json")

    def test_load_config_from_file_invalid_json(self) -> None:
        """Test config loading with invalid JSON."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config_file = f.name
            f.write("invalid json content")
        
        try:
            with pytest.raises(Exception):  # Should raise ClickException
                _load_config_from_file(config_file)
        finally:
            Path(config_file).unlink()

    def test_load_config_from_file_validation_error(self) -> None:
        """Test config loading with validation error."""
        config_data = {
            "default_approver": "admin"
            # Missing required lambda_function_url
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config_file = f.name
            json.dump(config_data, f)
        
        try:
            with pytest.raises(Exception):  # Should raise ClickException
                _load_config_from_file(config_file)
        finally:
            Path(config_file).unlink()

    def test_validate_config_success(self) -> None:
        """Test successful config validation."""
        config = ApprovalConfig(
            lambda_function_url="https://valid.lambda-url.aws.com"
        )
        
        # Should not raise any exception
        _validate_config(config)

    def test_validate_config_missing_url(self) -> None:
        """Test config validation with missing URL."""
        # This can't happen with normal Pydantic validation, but test the helper
        config = ApprovalConfig(
            lambda_function_url="https://test.lambda-url.aws.com"
        )
        config.lambda_function_url = ""  # Manually set to empty
        
        with pytest.raises(ValidationError):
            _validate_config(config)

    def test_validate_config_invalid_url(self) -> None:
        """Test config validation with invalid URL format."""
        config = ApprovalConfig(
            lambda_function_url="https://valid.lambda-url.aws.com"
        )
        config.lambda_function_url = "not-a-url"  # Manually set to invalid
        
        with pytest.raises(ValidationError):
            _validate_config(config)


if __name__ == "__main__":
    pytest.main([__file__]) 