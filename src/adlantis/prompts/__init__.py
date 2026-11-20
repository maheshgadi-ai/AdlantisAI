"""Agent prompts, one Markdown file per agent, versioned with the code."""

from __future__ import annotations

from functools import cache
from importlib import resources


@cache
def load_prompt(name: str) -> str:
    """Return the text of `prompts/<name>.md`.

    Raises:
        FileNotFoundError: If there is no prompt file with that name.
    """
    path = resources.files(__package__).joinpath(f"{name}.md")
    if not path.is_file():
        raise FileNotFoundError(f"No prompt file named {name}.md")
    return path.read_text(encoding="utf-8").strip()
