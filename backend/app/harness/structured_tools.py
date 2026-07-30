import json
from typing import Any

from pydantic import BaseModel, ValidationError


class StructuredOutputError(ValueError):
    pass


def structured_output_system(system: str, output_model: type[BaseModel]) -> str:
    schema = json.dumps(
        output_model.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        f"{system}\n\n"
        "完成所有必要工具调用后, 你必须只输出一个符合以下 JSON Schema 的 JSON 对象。"
        "不要输出 Markdown 代码块、解释、注释、前缀或后缀。"
        "输出必须能被标准 JSON 解析器直接解析。\n"
        f"JSON Schema:\n{schema}"
    )


def parse_structured_output[OutputT: BaseModel](
    content: str | None,
    output_model: type[OutputT],
) -> OutputT:
    if not content:
        raise StructuredOutputError("empty_structured_output")
    try:
        return output_model.model_validate(json.loads(content))
    except (json.JSONDecodeError, ValidationError) as error:
        raise StructuredOutputError("invalid_structured_output") from error


def anthropic_text(content: tuple[Any, ...]) -> str | None:
    parts = [
        str(block.text)
        for block in content
        if getattr(block, "type", None) == "text" and getattr(block, "text", None)
    ]
    return "".join(parts) or None
