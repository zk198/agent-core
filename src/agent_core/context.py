from typing import Any

class ContextBudget:
    def __init__(self, max_chars: int = 20_000, reserve_chars: int = 4_000) -> None:
        self.max_chars = max_chars
        self.reserve_chars = min(reserve_chars, max_chars)

    def bound(self, value: Any) -> str:
        text = str(value)
        limit = max(0, self.max_chars - self.reserve_chars)
        return text if len(text) <= limit else text[:limit] + "\n[truncated]"

def bound_text(value: Any, max_chars: int) -> str:
    return ContextBudget(max_chars, 0).bound(value)
