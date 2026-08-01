import pytest

from utils.settings import Settings


def test_gateway_limits_are_loaded_from_settings():
    settings = Settings.model_validate(
        {
            "model_max_concurrency": 3,
            "model_failure_threshold": 2,
            "model_cooldown_seconds": 4,
            "model_rate_limit_per_second": 10,
        }
    )
    assert settings.model_max_concurrency == 3
    assert settings.model_failure_threshold == 2
    assert settings.model_cooldown_seconds == 4
    assert settings.model_rate_limit_per_second == 10


@pytest.mark.parametrize("field", ["model_max_concurrency", "model_failure_threshold"])
def test_gateway_limits_reject_zero(field):
    with pytest.raises(ValueError):
        Settings.model_validate({field: 0})
