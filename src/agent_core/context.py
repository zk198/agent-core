from dataclasses import dataclass


@dataclass(frozen=True)
class ContextBudget:
    max_chars: int
    reserve: int

    def bound(self, text: str) -> str:
        budget = max(0, self.max_chars - self.reserve)
        if len(text) <= budget:
            return text
        return text[:budget] + "\n[tool result truncated]"

    def bound_messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        total = 0
        selected: list[dict[str, str]] = []
        for message in reversed(messages):
            size = len(message.get("content", ""))
            if selected and total + size > self.max_chars:
                break
            if not selected and size > self.max_chars:
                selected.append({"role": message["role"], "content": message["content"][-self.max_chars:]})
                break
            selected.append(message)
            total += size
        selected.reverse()
        return selected
