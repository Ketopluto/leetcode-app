from app.models import Student


def test_extract_username_plain():
    assert Student.extract_username_from_url("someuser") == "someuser"


def test_extract_username_from_u_path_url():
    assert Student.extract_username_from_url("https://leetcode.com/u/someuser/") == "someuser"


def test_extract_username_from_bare_profile_url():
    assert Student.extract_username_from_url("https://leetcode.com/someuser/") == "someuser"


def test_extract_username_strips_whitespace():
    assert Student.extract_username_from_url("  someuser  ") == "someuser"


def test_extract_username_empty_input():
    assert Student.extract_username_from_url("") is None
    assert Student.extract_username_from_url(None) is None
