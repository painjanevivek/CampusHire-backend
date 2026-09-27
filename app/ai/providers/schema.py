from typing import Any

from pydantic import BaseModel


def provider_response_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Send Gemini a structural schema; enforce domain constraints after generation."""
    schema = model.model_json_schema()
    definitions = schema.get("$defs", {})

    def project(node: dict[str, Any]) -> dict[str, Any]:
        reference = node.get("$ref")
        if isinstance(reference, str):
            return project(definitions[reference.rsplit("/", 1)[-1]])
        options = node.get("anyOf")
        if isinstance(options, list):
            non_null = [option for option in options if option.get("type") != "null"]
            if len(non_null) == 1 and len(non_null) != len(options):
                projected = project(non_null[0])
                projected["type"] = [projected["type"], "null"]
                return projected
        result: dict[str, Any] = {"type": node["type"]}
        if "enum" in node:
            result["enum"] = node["enum"]
        if "properties" in node:
            properties = {name: project(child) for name, child in node["properties"].items()}
            result["properties"] = properties
            result["required"] = list(properties)
        if "items" in node:
            result["items"] = project(node["items"])
        return result

    return project(schema)
