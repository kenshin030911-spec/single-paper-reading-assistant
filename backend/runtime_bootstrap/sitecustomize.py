"""
TEMP runtime patch for MinerU subprocesses on Windows.

`fasttext` may fail to open model files under non-ASCII user directories.
When the MinerU subprocess starts, redirect fast_langdetect's small model path
to an ASCII-safe copy prepared by the backend.
"""

from __future__ import annotations

import os
from pathlib import Path


fastlang_cache_dir = os.getenv("FTLANG_CACHE", "").strip()
if fastlang_cache_dir:
    os.environ["FTLANG_CACHE"] = fastlang_cache_dir

fastlang_small_model_path = os.getenv("FAST_LANGDETECT_SMALL_MODEL_PATH", "").strip()
if fastlang_small_model_path:
    try:
        import fast_langdetect.ft_detect.infer as infer

        patched_model_path = Path(fastlang_small_model_path)
        if patched_model_path.exists():
            infer.LOCAL_SMALL_MODEL_PATH = patched_model_path
            if fastlang_cache_dir:
                infer.CACHE_DIRECTORY = fastlang_cache_dir
    except Exception:
        # Keep the patch best-effort so startup is not blocked by this helper.
        pass
