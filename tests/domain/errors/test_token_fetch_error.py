from mergency.domain.errors.token_fetch_error import TokenFetchError


def test_token_fetch_error_message_includes_installation_id():
    cause = ValueError("bad credentials")

    error = TokenFetchError(42, cause)

    assert "42" in str(error)
    assert "bad credentials" in str(error)


def test_token_fetch_error_chains_the_original_exception():
    cause = ValueError("bad credentials")

    error = TokenFetchError(42, cause)

    assert error.installation_id == 42
    assert error.__cause__ is None  # not raised yet, so no __cause__ until `raise ... from`
