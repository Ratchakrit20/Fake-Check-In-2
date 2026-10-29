from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from backend.app.core.config import Settings, _apply_environment


def config_data():
    return yaml.safe_load((Path(__file__).parents[1] / "config" / "default.yaml").read_text(encoding="utf-8"))


def test_default_config_is_valid():
    settings = Settings.model_validate(config_data())
    assert settings.embedding.provider == "sscd"
    assert len(settings.embedding.model_sha256) == 64
    assert settings.vector_search.top_k == 30
    assert settings.jobs.worker_mode == "process"
    assert settings.ai_models_lat_long.model_path.name == "v1.pt"
    assert settings.ai_models_lat_long.lat_long_confidence == 0.90
    assert settings.ai_models_lat_long.datetime_enabled is True
    assert settings.ai_models_lat_long.datetime_confidence == 0.25
    assert settings.ai_models_lat_long.datetime_report_confidence == 0.95


def test_celery_worker_mode_is_configurable():
    data = config_data()
    for mode in ("inline", "process", "celery"):
        data = config_data()
        data["jobs"]["worker_mode"] = mode
        assert Settings.model_validate(data).jobs.worker_mode == mode


def test_invalid_threshold_order_fails_fast():
    data = config_data()
    data["relationship"]["high_threshold"] = 0.95
    with pytest.raises(ValidationError):
        Settings.model_validate(data)


def test_environment_can_override_nested_weight(monkeypatch):
    data = config_data()
    monkeypatch.setenv("RELATIONSHIP__WEIGHTS__PHASH", "0.20")
    monkeypatch.setenv("RELATIONSHIP__WEIGHTS__EMBEDDING", "0.40")
    overridden = _apply_environment(data)

    assert overridden["relationship"]["weights"]["phash"] == 0.20
    assert overridden["relationship"]["weights"]["embedding"] == 0.40
    Settings.model_validate(overridden)

