import keyring
import pytest

from github_stars.config import Paths


def unavailable(*_args):
    raise keyring.errors.NoKeyringError("No credential backend")


def test_anonymous_github_without_credential_backend(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(keyring, "get_password", unavailable)
    assert Paths(tmp_path).secret("github") == ""


@pytest.mark.parametrize("kind,name", [("github", "GITHUB_TOKEN"), ("openai", "OPENAI_API_KEY"),
                                      ("smtp", "GITHUB_STARS_SMTP_PASSWORD")])
def test_environment_credentials_do_not_need_backend(tmp_path, monkeypatch, kind, name):
    monkeypatch.setenv(name, "test-only-placeholder")
    monkeypatch.setattr(keyring, "get_password", unavailable)
    assert Paths(tmp_path).secret(kind, source="local") == "test-only-placeholder"


@pytest.mark.parametrize("kind,name", [("openai", "OPENAI_API_KEY"), ("smtp", "GITHUB_STARS_SMTP_PASSWORD")])
def test_required_credentials_report_missing_backend(tmp_path, monkeypatch, kind, name):
    monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(keyring, "get_password", unavailable)
    with pytest.raises(ValueError, match=name):
        Paths(tmp_path).secret(kind, source="local")


def test_existing_backend_error_is_not_treated_as_anonymous(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    def locked(*_args):
        raise keyring.errors.KeyringError("locked backend")

    monkeypatch.setattr(keyring, "get_password", locked)
    with pytest.raises(keyring.errors.KeyringError, match="locked backend"):
        Paths(tmp_path).secret("github")


def test_failed_secret_storage_never_writes_yaml(tmp_path, monkeypatch):
    paths = Paths(tmp_path)
    monkeypatch.setattr(keyring, "set_password", unavailable)
    with pytest.raises(ValueError, match="密钥未保存"):
        paths.set_secret("openai", "test-only-placeholder")
    assert not paths.settings.exists()
