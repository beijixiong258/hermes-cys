"""Tests for xAI Imagine storage helper behavior."""

from __future__ import annotations

import yaml


def _invalidate_config_cache():
    try:
        import hermes_cli.config as cfg_mod

        if hasattr(cfg_mod, "_invalidate_load_config_cache"):
            cfg_mod._invalidate_load_config_cache()
    except Exception:
        pass


def test_storage_defaults_to_permanent_public_urls(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _invalidate_config_cache()

    from tools.xai_http import build_xai_storage_options

    storage = build_xai_storage_options(
        "image_gen",
        filename_prefix="hermes-xai-image",
        extension="png",
    )

    assert storage is not None
    assert storage["public_url"] is True
    assert "expires_after" not in storage
    assert storage["filename"].startswith("hermes-xai-image-")
    assert storage["filename"].endswith(".png")

