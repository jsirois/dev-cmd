# Copyright 2025 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dev_cmd.expansion import expand


def test_expand_noop() -> None:
    assert ("",) == expand("")
    assert ("foo",) == expand("foo")

    assert ("foo,bar",) == expand("foo,bar")
    assert ("0..1",) == expand("0..1")

    assert ("{foo,bar",) == expand("{{foo,bar")
    assert ("foo,bar}",) == expand("foo,bar}")
    assert ("{foo,bar}",) == expand("{{foo,bar}")


def test_expand_enumeration() -> None:
    assert ("", "") == expand("{,}")
    assert ("a", "") == expand("{a,}")
    assert ("", "a") == expand("{,a}")

    assert ("a", "a") == expand("{a,a}")

    assert ("a", "1", "2") == expand("{a,{1,2}}")
    assert ("a", "b1", "b2") == expand("{a,b{1,2}}")
    assert ("a", "1b", "2b") == expand("{a,{1,2}b}")
    assert ("a", "a1b", "a2b") == expand("{a,a{1,2}b}")
    assert ("a1b", "a2Ab", "a2Bb") == expand("{a{1,2{A,B}}b}")

    assert ("ac", "ad", "bc", "bd") == expand("{a,b}{c,d}")
    assert ("ace", "acf", "ade", "adf", "bce", "bcf", "bde", "bdf") == expand("{a,b}{c,d}{e,f}")


def test_expand_range() -> None:
    assert ("0",) == expand("{0..0}")

    assert ("0", "1") == expand("{0..1}")
    assert ("1", "0") == expand("{1..0}")

    assert ("-1", "0", "1") == expand("{-1..1}")
    assert ("1", "0", "-1") == expand("{1..-1}")

    assert ("1", "3", "5") == expand("{1..5..2}")
    assert ("v1", "v3", "v5") == expand("v{1..5..2}")

    assert () == expand("{1..5..-2}")
    assert () == expand("v{1..5..-2}")


def test_expand_mixed() -> None:
    assert ("pre-a-post", "pre-b-post", "pre-c1-post", "pre-c3-post") == expand(
        "pre-{a,b,c{1..3..2}}-post"
    )

    # N.B.: This matches bash / zsh behavior - range expansions do not recurse like enumeration
    # expansions do.
    assert ("3..1", "3..5") == expand("3..{1,5}")
    assert ("3..1", "3..5") == expand("{3..{1,5}}")
