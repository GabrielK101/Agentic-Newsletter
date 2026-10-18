import inspect
import json
from typing import get_type_hints

_TYPE_MAP = {str: "string", int: "integer", float: "number", bool: "boolean"}
REGISTRY: dict = {}

def tool(fn):
    hints = get_type_hints(fn)
    hints.pop("return", None)
    props, required = {}, []
    for name, param in inspect.signature(fn).parameters.items():
        py_type = hints.get(name)
        if py_type not in _TYPE_MAP:
            raise TypeError(
                f"@tool {fn.__name__}: parameter '{name}' has unsupported type "
                f"{py_type!r}; supported types are {list(_TYPE_MAP)}"
            )
        props[name] = {"type": _TYPE_MAP[py_type]}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    REGISTRY[fn.__name__] = {
        "fn": fn,
        "schema": {
            "name": fn.__name__,
            "description": inspect.getdoc(fn),
            "input_schema": {
                "type": "object",
                "properties": props,
                "required": required,
            },
        },
    }
    return fn

def schemas() -> list:
    return [t["schema"] for t in REGISTRY.values()]


def run_tool(name: str, args: dict) -> str:
    if name not in REGISTRY:
        return f"Error: unknown tool '{name}'"
    try:
        return REGISTRY[name]["fn"](**args)
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"