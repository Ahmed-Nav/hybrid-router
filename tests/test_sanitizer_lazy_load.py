import sanitizer


def test_analyzer_is_not_loaded_at_import_time():
    # Reload sanitizer fresh, without calling initialize_sanitizer, to verify
    # it does NOT eagerly build the analyzer at import time anymore.
    import importlib
    fresh_sanitizer = importlib.reload(sanitizer)
    assert fresh_sanitizer.analyzer is None
    # Restore real initialization for any tests that run after this one in the same session.
    fresh_sanitizer.initialize_sanitizer()


def test_initialize_sanitizer_sets_up_a_working_analyzer():
    sanitizer.initialize_sanitizer()
    assert sanitizer.analyzer is not None
    result = sanitizer.sanitize_prompt("Email me at test@example.com")
    assert "test@example.com" not in result
