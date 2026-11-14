from utils.auth import check, expected_hashes, hash_password


def test_plain_and_hashed_passwords_are_accepted():
    hashes = expected_hashes({"APP_PASSWORDS": ["alpha", "beta"], "APP_PASSWORDS_SHA256": [hash_password("gamma")]})
    assert check("alpha", hashes) and check("beta", hashes) and check("gamma", hashes)


def test_wrong_or_empty_password_is_rejected():
    hashes = expected_hashes({"APP_PASSWORDS": ["alpha"]})
    assert not check("Alpha", hashes)
    assert not check("", hashes)


def test_no_configured_password_locks_the_app():
    assert expected_hashes({}) == []
    assert not check("anything", [])
    assert expected_hashes({"APP_PASSWORDS": ["", "  "]}) == []
