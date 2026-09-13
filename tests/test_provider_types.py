from jimmy.llm.types import Message, Usage


def test_message_and_usage_types() -> None:
    message = Message(role="user", content="hello")
    usage = Usage(input_tokens=1, output_tokens=2, total_tokens=3)
    assert message.role == "user"
    assert usage.total_tokens == 3
