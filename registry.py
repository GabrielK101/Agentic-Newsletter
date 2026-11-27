import inspect
import json
from typing import get_args, get_origin, get_type_hints

_TYPE_MAP = {str: "string", int: "integer", float: "number", bool: "boolean"}
REGISTRY: dict = {}

def _schema_for(py_type, fn_name: str, param_name: str) -> dict:
    if py_type in _TYPE_MAP:
        return {"type": _TYPE_MAP[py_type]}
    if get_origin(py_type) is list:
        args = get_args(py_type)
        item_type = args[0] if args else str
        if item_type in _TYPE_MAP:
            return {"type": "array", "items": {"type": _TYPE_MAP[item_type]}}
    raise TypeError(
        f"@tool {fn_name}: parameter '{param_name}' has unsupported type "
        f"{py_type!r}; supported types are {list(_TYPE_MAP)} or list[<one of those>]"
    )

def tool(fn):
    hints = get_type_hints(fn)
    hints.pop("return", None)
    props, required = {}, []
    for name, param in inspect.signature(fn).parameters.items():
        props[name] = _schema_for(hints.get(name), fn.__name__, name)
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