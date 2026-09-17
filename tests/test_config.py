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
    assert settings.person_segmentation.model_path.name == "yolo26s-seg.pt"
    assert settings.person_segmentation.confidence == 0.35


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

