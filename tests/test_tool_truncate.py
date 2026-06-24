"""
tool_truncate 测试 —— 阈值、环境变量、中文字符。
"""

import pytest

from src.persistence.tool_truncate import truncate_dict_fields, truncate_for_persist


class TestBasicTruncate:
    def test_short_returned_as_is(self):
        assert truncate_for_persist("hello", limit=100) == "hello"

    def test_long_truncated_with_note(self):
        text = "x" * 100
        out = truncate_for_persist(text, limit=10)
        assert out.startswith("x" * 10)
        assert "[已截断，原文 100 字符]" in out

    def test_exact_limit_not_truncated(self):
        text = "y" * 10
        assert truncate_for_persist(text, limit=10) == text

    def test_chinese_chars_count_by_codepoint(self):
        # 中文逐字符计数，不按 UTF-8 字节
        text = "你好世界你好世界你好世界"  # 12 个字符
        out = truncate_for_persist(text, limit=5)
        assert out.startswith("你好世界你")
        assert "[已截断，原文 12 字符]" in out

    def test_zero_limit_disables_truncation(self):
        text = "abc" * 1000
        assert truncate_for_persist(text, limit=0) == text

    def test_negative_limit_disables_truncation(self):
        text = "abc" * 1000
        assert truncate_for_persist(text, limit=-1) == text

    def test_none_input_returns_empty(self):
        assert truncate_for_persist(None) == ""

    def test_non_str_cast(self):
        out = truncate_for_persist(12345, limit=3)
        assert out.startswith("123")


class TestEnvOverride:
    def test_env_var_overrides_default(self, monkeypatch):
        monkeypatch.setenv("TOOL_PERSIST_MAX_CHARS", "5")
        out = truncate_for_persist("0123456789")
        assert out.startswith("01234")
        assert "[已截断" in out

    def test_invalid_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("TOOL_PERSIST_MAX_CHARS", "not_an_int")
        # 默认 4000，短文本不动
        assert truncate_for_persist("short") == "short"

    def test_explicit_limit_beats_env(self, monkeypatch):
        monkeypatch.setenv("TOOL_PERSIST_MAX_CHARS", "100")
        out = truncate_for_persist("x" * 50, limit=10)
        assert "[已截断" in out


class TestTruncateDictFields:
    def test_only_target_fields_processed(self):
        data = {
            "content": "a" * 100,
            "reason": "ok",
            "result": "b" * 50,
            "other_field": "c" * 100,    # 不应被截断
        }
        truncate_dict_fields(data, fields=("content", "reason"), limit=10)
        assert "[已截断" in data["content"]
        assert data["reason"] == "ok"
        assert data["result"] == "b" * 50              # 不在 fields 列表
        assert data["other_field"] == "c" * 100        # 不在 fields 列表

    def test_missing_field_safe(self):
        data = {"content": "short"}
        # 不抛
        truncate_dict_fields(data, fields=("content", "reason"))
        assert data["content"] == "short"

    def test_non_string_field_skipped(self):
        data = {"content": 12345}    # 非 str
        truncate_dict_fields(data, fields=("content",), limit=2)
        assert data["content"] == 12345    # 原样保留
