from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input_per_million: Decimal
    output_per_million: Decimal
    cache_write_per_million: Decimal
    cache_read_per_million: Decimal


PRICES: dict[str, ModelPrice] = {
    "claude-opus-4-8": ModelPrice(
        input_per_million=Decimal("5"),
        output_per_million=Decimal("25"),
        cache_write_per_million=Decimal("6.25"),
        cache_read_per_million=Decimal("0.50"),
    )
}


def estimate_cost(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> Decimal:
    price = PRICES.get(model)
    if price is None:
        return Decimal(0)
    million = Decimal(1_000_000)
    return (
        Decimal(input_tokens) * price.input_per_million
        + Decimal(output_tokens) * price.output_per_million
        + Decimal(cache_creation_input_tokens) * price.cache_write_per_million
        + Decimal(cache_read_input_tokens) * price.cache_read_per_million
    ) / million
