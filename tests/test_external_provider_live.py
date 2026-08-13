import os

import pytest

from market_evolver.external.provider import DeepSeekProvider
from market_evolver.external.schemas import ExecutionStatus


@pytest.mark.live
@pytest.mark.external_provider
def test_live_deepseek_minimal_structured_validation() -> None:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY is not configured")
    assert DeepSeekProvider().validate().status is ExecutionStatus.PASS
