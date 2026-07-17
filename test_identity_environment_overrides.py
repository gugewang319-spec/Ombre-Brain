from identity import identity_names
from utils import load_config


def _isolated_config(monkeypatch, tmp_path, identity_yaml: str):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(identity_yaml, encoding="utf-8")
    monkeypatch.setenv("OMBRE_BUCKETS_DIR", str(tmp_path / "buckets"))
    monkeypatch.setenv("OMBRE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("OMBRE_RUNTIME_CONFIG_PATH", raising=False)
    return load_config(str(config_path))


def test_identity_uses_config_values_without_environment_overrides(monkeypatch, tmp_path):
    for env_name in ("OMBRE_AI_NAME", "OMBRE_USER_NAME", "OMBRE_USER_DISPLAY_NAME"):
        monkeypatch.delenv(env_name, raising=False)

    config = _isolated_config(
        monkeypatch,
        tmp_path,
        """identity:
  ai_name: Config AI
  user_name: Config User
  user_display_name: Config Display
""",
    )

    assert identity_names(config)["ai_name"] == "Config AI"
    assert identity_names(config)["user_name"] == "Config User"
    assert identity_names(config)["user_display_name"] == "Config Display"


def test_identity_environment_overrides_config_for_shared_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("OMBRE_AI_NAME", "Environment AI")
    monkeypatch.setenv("OMBRE_USER_NAME", "Environment User")
    monkeypatch.setenv("OMBRE_USER_DISPLAY_NAME", "Environment Display")

    config = _isolated_config(
        monkeypatch,
        tmp_path,
        """identity:
  ai_name: Config AI
  user_name: Config User
  user_display_name: Config Display
""",
    )
    names = identity_names(config)

    assert config["identity"] == {
        "ai_name": "Environment AI",
        "user_name": "Environment User",
        "user_display_name": "Environment Display",
        "user_aliases": ["对方"],
    }
    assert names["ai_name"] == "Environment AI"
    assert names["user_name"] == "Environment User"
    assert names["user_display_name"] == "Environment Display"
