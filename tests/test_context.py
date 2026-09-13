from jimmy.context import ContextBuilder


def test_context_contains_system_and_user_message() -> None:
    messages = ContextBuilder().build("hello")
    assert messages[0].role == "system"
    assert "Jimmy" in messages[0].content
    assert messages[-1].role == "user"
    assert messages[-1].content == "hello"
