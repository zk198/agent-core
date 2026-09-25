from agent_core.context import bound_text

def test_bound_text_keeps_small_values():
    assert bound_text("abc", 3) == "abc"

def test_bound_text_truncates_large_values():
    assert bound_text("abcdef", 3).endswith("[truncated]")


def test_context_budget_bounds_result():
    from agent_core.context import ContextBudget
    assert ContextBudget(3).bound("abcdef").endswith("[truncated]")
