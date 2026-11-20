import pytest

from adlantis.config import Pricing
from adlantis.llm import RunUsage, Usage
from adlantis.llm.pricing import cost_of


def test_cost_of() -> None:
    pricing = Pricing(input_per_mtok=1.0, output_per_mtok=4.0)
    assert cost_of(Usage(input_tokens=2_000_000, output_tokens=500_000), pricing) == (2.0, 2.0)
    assert cost_of(Usage(input_tokens=10, output_tokens=10), Pricing()) == (0.0, 0.0)


def test_run_usage_totals_and_breakdown() -> None:
    run = RunUsage()
    run.record(Usage(input_tokens=100, output_tokens=50), 0.5, role="copywriter")
    run.record(Usage(input_tokens=10, output_tokens=5), 0.1, role="judge")
    run.record(Usage(input_tokens=1, output_tokens=1), role="copywriter")

    assert (run.calls, run.total_tokens) == (3, 167)
    assert run.cost_usd == 0.6
    assert run.by_role["copywriter"].calls == 2
    assert run.by_role["judge"].cost_usd == 0.1


def test_cache_prices_fall_back_to_input_price_when_unknown() -> None:
    usage = Usage(input_tokens=1_000_000, cache_read_tokens=600_000, cache_write_tokens=0)
    assert cost_of(usage, Pricing(input_per_mtok=1.0)) == (1.0, 0.0)  # conservative
    priced = Pricing(input_per_mtok=1.0, cache_read_per_mtok=0.05)
    assert cost_of(usage, priced)[0] == pytest.approx(0.4 + 0.6 * 0.05)


def test_catalog_has_anthropic_cache_prices() -> None:
    from adlantis.config import load_models_config

    cfg = load_models_config()
    opus, sonnet = cfg.price_for("claude-opus-5-5"), cfg.price_for("claude-sonnet-5-5")
    assert (opus.cache_read_per_mtok, opus.cache_write_per_mtok) == (0.20, 5.0)
    assert (sonnet.cache_read_per_mtok, sonnet.cache_write_per_mtok) == (0.10, 2.5)


def test_catalog_has_openai_cache_prices() -> None:
    from adlantis.config import load_models_config

    sol = load_models_config().price_for("gpt-6.2-sol")
    assert (sol.cache_read_per_mtok, sol.cache_write_per_mtok) == (0.10, 2.5)
