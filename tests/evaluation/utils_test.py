from slop_code.evaluation import utils


def test_deep_merge_dicts_basic():
    """Test nested merge behavior where overrides replace or deep-merge values."""
    base = {"a": 1, "b": {"x": 1, "y": 2}, "c": {"k": 1}}
    over = {"b": {"y": 99, "z": 3}, "c": 42, "d": 7}
    out = utils.nested_priority_merge(base, over)
    assert out == {
        "a": 1,
        "b": {
            "x": 1,
            "y": 99,
            "z": 3,
        },  # dict-on-dict deep merge, override wins
        "c": 42,  # override non-dict replaces dict
        "d": 7,
    }
