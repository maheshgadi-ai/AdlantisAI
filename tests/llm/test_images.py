"""Image generation calls the configured model, inside the budget."""

import base64
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
import yaml

from adlantis.config import ConfigurationError, Settings, load_profile
from adlantis.config.images import IMAGE_CONFIG_PATH, load_image_config
from adlantis.config.models import DEPRECATIONS_PATH
from adlantis.llm import LLMError, ModelRouter
from adlantis.llm.budget import BudgetCap, BudgetExceeded
from adlantis.llm.images import ImageGenerator

CONFIG = load_image_config()
PNG = b"\x89PNG fake"


def usage() -> NS:
    return NS(
        input_tokens=100,
        output_tokens=1000,
        input_tokens_details=NS(text_tokens=80, image_tokens=20),
    )


def reply(data: bytes = PNG, used=None) -> NS:
    return NS(data=[NS(b64_json=base64.b64encode(data).decode())], usage=used or usage())


class Images:
    def __init__(self, result) -> None:
        self.result = result
        self.calls: list[dict] = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def generator(result=None, budget=None):
    images = Images(reply() if result is None else result)
    return ImageGenerator(CONFIG, NS(images=images), budget=budget), images


def test_configured_model_is_current() -> None:
    deprecated = yaml.safe_load(DEPRECATIONS_PATH.read_text())["deprecated"]
    assert CONFIG.model not in deprecated
    assert {"dall-e-3", "gpt-image-1", "gpt-image-2"} <= set(deprecated)


def test_images_are_off_by_default() -> None:
    assert Settings(_env_file=None).enable_images is False


def test_retired_model_is_refused(tmp_path: Path) -> None:
    data = yaml.safe_load(IMAGE_CONFIG_PATH.read_text())
    price = data["pricing"][data["image"]["model"]]
    data["image"]["model"] = "dall-e-3"
    data["pricing"] = {"dall-e-3": price}
    path = tmp_path / "images.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ConfigurationError, match="dall-e-3 is deprecated"):
        load_image_config(path)


def test_invalid_config_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "images.yaml"
    path.write_text("image: {}\n")
    with pytest.raises(ConfigurationError, match="Invalid image config"):
        load_image_config(path)


def test_channel_sizes_come_from_config() -> None:
    assert CONFIG.size_for("instagram") == "1024x1024"
    assert CONFIG.size_for("landing_page") == "1536x1024"
    assert CONFIG.size_for("search_ad") == CONFIG.default_size


def test_request_uses_the_configured_settings() -> None:
    made, images = generator()
    made.generate("A table.", "1536x1024")
    assert images.calls == [
        {
            "model": CONFIG.model,
            "prompt": "A table.",
            "size": "1536x1024",
            "quality": CONFIG.quality,
            "n": 1,
            "output_format": "png",
        }
    ]


def test_image_is_decoded_and_priced_from_usage() -> None:
    made, _ = generator()
    result = made.generate("A table.", "1024x1024")
    expected = (80 * 5 + 20 * 8 + 1000 * 30) / 1_000_000
    assert (result.data, result.model) == (PNG, CONFIG.model)
    assert result.cost_usd == pytest.approx(expected)


def test_missing_usage_is_charged_the_full_reserve() -> None:
    made, _ = generator(NS(data=reply().data, usage=None))
    assert made.generate("A table.", "1024x1024").cost_usd == CONFIG.reserve_usd_per_image


def test_cost_is_charged_to_the_budget_and_the_hold_released() -> None:
    budget = BudgetCap(1.0)
    made, _ = generator(budget=budget)
    result = made.generate("A table.", "1024x1024")
    assert budget.other_usd == pytest.approx(result.cost_usd)
    assert budget._holds == 0


def test_image_that_could_pass_the_cap_is_never_requested() -> None:
    made, images = generator(budget=BudgetCap(CONFIG.reserve_usd_per_image / 2))
    with pytest.raises(BudgetExceeded):
        made.generate("A table.", "1024x1024")
    assert images.calls == []


def test_provider_failure_becomes_an_llm_error_and_releases_the_hold() -> None:
    budget = BudgetCap(1.0)
    made, _ = generator(RuntimeError("secret detail"), budget)
    with pytest.raises(LLMError, match="RuntimeError") as caught:
        made.generate("A table.", "1024x1024")
    assert "secret detail" not in str(caught.value)
    assert budget._holds == 0


@pytest.mark.parametrize(
    "result", [NS(data=[], usage=None), NS(data=[NS(b64_json=None)], usage=None)]
)
def test_response_without_an_image_is_an_error(result) -> None:
    made, _ = generator(result)
    with pytest.raises(LLMError, match="no image data"):
        made.generate("A table.", "1024x1024")


@pytest.mark.parametrize("encoded", ["not base64!", "QUJD!"])
def test_unreadable_image_data_is_an_error(encoded: str) -> None:
    made, _ = generator(NS(data=[NS(b64_json=encoded)], usage=None))
    with pytest.raises(LLMError, match="unreadable"):
        made.generate("A table.", "1024x1024")


def test_router_shares_its_budget_with_the_generator() -> None:
    client = NS(images=Images(reply()))
    router = ModelRouter(
        Settings(_env_file=None),
        load_profile("budget"),
        client_factory=lambda _provider: client,
        max_cost_usd=2.0,
    )
    router.image_generator().generate("A table.", "1024x1024")
    assert router.budget.other_usd > 0
