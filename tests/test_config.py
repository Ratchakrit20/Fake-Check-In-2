from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from backend.app.core.config import Settings


def config_data():
    return yaml.safe_load((Path(__file__).parents[1] / "config" / "default.yaml").read_text(encoding="utf-8"))


def test_default_config_is_valid():
    settings = Settings.model_validate(config_data())
    assert settings.embedding.provider == "sscd"
    assert len(settings.embedding.model_sha256) == 64
    assert settings.vector_search.top_k == 30


def test_invalid_threshold_order_fails_fast():
    data = config_data()
    data["relationship"]["high_threshold"] = 0.95
    with pytest.raises(ValidationError):
        Settings.model_validate(data)

