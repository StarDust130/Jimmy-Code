from jimmy.state.session import SessionState


def test_session_starts_with_empty_state() -> None:
    state = SessionState(task="Fix login")

    assert state.task == "Fix login"
    assert state.messages == []
    assert state.turn_count == 0


def test_session_adds_messages() -> None:
    state = SessionState(task="Fix login")

    state.add_message(
        {
            "role": "user",
            "content": "Fix login",
        }
    )

    assert len(state.messages) == 1
    assert state.messages[0]["content"] == "Fix login"


def test_session_turns_increment() -> None:
    state = SessionState(task="Fix login")

    assert state.next_turn() == 1
    assert state.next_turn() == 2
    assert state.turn_count == 2
