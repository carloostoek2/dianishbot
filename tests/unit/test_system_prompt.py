"""Tests for external system prompt loading."""

from pathlib import Path

import config


def test_load_system_prompt_reads_md_file(tmp_path):
    path = tmp_path / "prompt.md"
    path.write_text("  Soy Diana.\n", encoding="utf-8")
    config.reset_system_prompt_cache()

    text = config.load_system_prompt(path=path, force=True)

    assert text == "Soy Diana."
    assert config.get_system_prompt() == "Soy Diana."
    config.reset_system_prompt_cache()


def test_load_system_prompt_missing_file_raises(tmp_path):
    config.reset_system_prompt_cache()
    missing = tmp_path / "missing.md"

    try:
        config.load_system_prompt(path=missing, force=True)
        assert False, "expected FileNotFoundError"
    except FileNotFoundError as e:
        assert str(missing) in str(e)
    finally:
        config.reset_system_prompt_cache()


def test_load_system_prompt_empty_file_raises(tmp_path):
    path = tmp_path / "empty.md"
    path.write_text("   \n", encoding="utf-8")
    config.reset_system_prompt_cache()

    try:
        config.load_system_prompt(path=path, force=True)
        assert False, "expected ValueError"
    except ValueError as e:
        assert str(path) in str(e)
    finally:
        config.reset_system_prompt_cache()