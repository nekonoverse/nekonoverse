from app.utils.emoji import is_single_emoji


def test_simple_emoji():
    assert is_single_emoji("\U0001f600")


def test_heart():
    assert is_single_emoji("\u2764")


def test_flag_emoji():
    assert is_single_emoji("\U0001f1ef\U0001f1f5")


def test_zwj_family():
    assert is_single_emoji("\U0001f468\u200d\U0001f469\u200d\U0001f467\u200d\U0001f466")


def test_skin_tone():
    assert is_single_emoji("\U0001f44d\U0001f3fd")


def test_star():
    assert is_single_emoji("\u2b50")


def test_empty_string():
    assert not is_single_emoji("")


def test_regular_text():
    assert not is_single_emoji("hello")


def test_emoji_with_text():
    assert not is_single_emoji("\U0001f600hello")


def test_multiple_emoji():
    assert not is_single_emoji("\U0001f600\U0001f600")


def test_long_string():
    assert not is_single_emoji("a" * 21)


def test_whitespace_stripped():
    assert is_single_emoji(" \U0001f600 ")
