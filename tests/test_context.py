from jimmy.context.context import ContextConfig, ContextManager


def test_small_context_is_unchanged() -> None:
    manager = ContextManager()

    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "hello"},
    ]

    result = manager.prepare(messages)

    assert result == messages


def test_large_message_is_truncated() -> None:
    manager = ContextManager(
        config=ContextConfig(
            max_message_chars=10,
        )
    )

    result = manager.prepare(
        [
            {
                "role": "user",
                "content": "a" * 100,
            }
        ]
    )

    assert len(result[0]["content"]) > 10
    assert "[message truncated]" in result[0]["content"]


def test_message_count_is_limited() -> None:
    manager = ContextManager(
        config=ContextConfig(
            max_messages=5,
        )
    )

    messages = [
        {
            "role": "user",
            "content": str(index),
        }
        for index in range(10)
    ]

    result = manager.prepare(messages)

    assert len(result) <= 5
