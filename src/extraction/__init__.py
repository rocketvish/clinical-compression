"""Local clinical fact extraction toolkit.

Public functions are re-exported lazily (PEP 562). Eagerly importing the
`validate`/`merge` submodules here would make `python -m src.extraction.validate`
double-import the module (runpy RuntimeWarning), so we resolve names on demand.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

__all__ = [
    "build_system_prompt",
    "build_extraction_prompt",
    "build_verification_prompt",
    "validate_response",
    "merge_facts",
]

_EXPORTS = {
    "build_system_prompt": ".prompts",
    "build_extraction_prompt": ".prompts",
    "build_verification_prompt": ".prompts",
    "validate_response": ".validate",
    "merge_facts": ".merge",
}


def __getattr__(name: str):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(module, __name__), name)


def __dir__() -> list[str]:
    return sorted(__all__)


if TYPE_CHECKING:  # for type checkers / IDEs only — not executed at runtime
    from .merge import merge_facts
    from .prompts import (
        build_extraction_prompt,
        build_system_prompt,
        build_verification_prompt,
    )
    from .validate import validate_response
