from agent_core.context import bound_text

def test_bound_text_keeps_small_values():
    assert bound_text("abc", 3) == "abc"

def test_bound_text_truncates_large_values():
    assert bound_text("abcdef", 3).endswith("[truncated]")
    assert len(bound_text("abcdef", 3)) > 3
