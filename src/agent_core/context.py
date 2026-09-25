from typing import Any

def bound_text(value: Any, max_chars: int) -> str:
    text = str(value)
    return text if len(text) <= max_chars else text[:max_chars] + "\n[truncated]"
