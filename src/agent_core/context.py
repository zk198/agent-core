from typing import Any

class ContextBudget:
    def __init__(self, max_chars: int = 20_000) -> None:
        self.max_chars = max_chars

    def bound(self, value: Any) -> str:
        text = str(value)
        return text if len(text) <= self.max_chars else text[:self.max_chars] + "\n[truncated]"

def bound_text(value: Any, max_chars: int) -> str:
    return ContextBudget(max_chars).bound(value)
