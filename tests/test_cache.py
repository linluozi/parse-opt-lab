"""Behavioural tests for the semantics-keyed Parser cache.

The patched tree is expected at ``../patched`` (that is what the README's
reproduce step creates); override with ``PARSE_SRC=/path/to/patched``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

DEFAULT = Path(__file__).resolve().parents[1] / "patched"
SRC = Path(os.environ.get("PARSE_SRC", DEFAULT)).resolve()
if not SRC.is_dir():
    pytest.skip(f"patched tree not found at {SRC}", allow_module_level=True)
sys.path.insert(0, str(SRC))
import parse  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_cache():
    parse.parser_cache_clear()
    yield
    parse.parser_cache_clear()


def test_repeated_format_hits_cache_and_returns_same_values():
    first = parse.parse("Package: {name}", "Package: libc6")
    info1 = parse.parser_cache_info()
    second = parse.parse("Package: {name}", "Package: libc6")
    info2 = parse.parser_cache_info()
    assert first.named == second.named == {"name": "libc6"}
    assert info2.hits == info1.hits + 1
    assert info2.currsize == 1


def test_converter_identity_is_part_of_the_key():
    assert parse.parse("{word:w}", "abc", extra_types={"w": str.upper}).named["word"] == "ABC"
    assert parse.parse("{word:w}", "abc", extra_types={"w": str.lower}).named["word"] == "abc"
    # exact same semantics must hit, not miss
    assert parse.parse("{word:w}", "abc", extra_types={"w": str.upper}).named["word"] == "ABC"
    info = parse.parser_cache_info()
    assert info.currsize == 2
    assert info.hits == 1


def test_format_only_cache_would_be_wrong():
    # A naive cache keyed only on the format string would reuse the first
    # Parser (with the upper converter) for the plain call.  That is wrong.
    naive = parse.Parser("{word:w}", extra_types={"w": str.upper})
    assert naive.parse("abc").named["word"] == "ABC"
    assert parse.parse("{word:w}", "abc").named["word"] == "abc"


def test_case_sensitivity_is_part_of_the_key():
    assert parse.parse("abc", "ABC") is not None
    assert parse.parse("abc", "ABC", case_sensitive=True) is None
    assert parse.parser_cache_info().currsize == 2


def test_unhashable_extra_types_falls_back_without_error():
    class Converter:
        __hash__ = None  # type: ignore[assignment]

        def __call__(self, text):
            return text + "!"

    conv = Converter()
    a = parse.parse("{word:w}", "abc", extra_types={"w": conv})
    b = parse.parse("{word:w}", "abc", extra_types={"w": conv})
    assert a.named["word"] == b.named["word"] == "abc!"
    assert parse.parser_cache_info().currsize == 0


def test_cache_is_bounded():
    for i in range(300):
        assert parse.parse("{x}", f"v{i}").named["x"] == f"v{i}"
    assert parse.parser_cache_info().currsize <= 256


def test_search_shares_the_cache():
    assert parse.search("id={n:d}", "x id=42 y").named["n"] == 42
    first = parse.parser_cache_info().currsize
    assert parse.search("id={n:d}", "z id=7").named["n"] == 7
    info = parse.parser_cache_info()
    assert info.currsize == first == 1
    assert info.hits == 1


def test_cached_result_equals_fresh_parser_result():
    fmt = "Package: {name} | Version: {v}"
    string = "Package: libc6 | Version: 2.39-0ubuntu8.6"
    cached = parse.parse(fmt, string)
    fresh = parse.Parser(fmt).parse(string)
    assert cached.fixed == fresh.fixed
    assert cached.named == fresh.named
    assert cached.spans == fresh.spans
