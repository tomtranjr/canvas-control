from __future__ import annotations

import getpass
import os
from dataclasses import dataclass
from typing import Literal

from rich.console import Console

TOKEN_ENV_VAR = "CANVAS_TOKEN"


@dataclass(slots=True)
class TokenInfo:
    token: str
    source: Literal["env", "prompt"]


class AuthError(ValueError):
    """Raised when token resolution fails."""


def resolve_token(console: Console) -> TokenInfo:
    token = os.getenv(TOKEN_ENV_VAR)
    if token:
        return TokenInfo(token=token.strip(), source="env")
    return prompt_for_token(console)


def prompt_for_token(console: Console) -> TokenInfo:
    console.print(
        f"[bold]Canvas token required[/bold] (set {TOKEN_ENV_VAR} to skip prompts)."
    )
    token = getpass.getpass("Canvas API token: ").strip()
    if not token:
        raise AuthError("Canvas token cannot be empty.")
    return TokenInfo(token=token, source="prompt")
