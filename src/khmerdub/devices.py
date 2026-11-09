"""GPU detection shared by Demucs (torch) and Whisper (ctranslate2)."""

from __future__ import annotations

import functools
import os
import shutil
import sys


def has_nvidia_gpu() -> bool:
    """Quick check (no torch import): is an NVIDIA driver installed?"""
    return shutil.which("nvidia-smi") is not None


@functools.cache
def torch_device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


@functools.cache
def prepare_cuda_for_ctranslate2() -> bool:
    """Make the CUDA/cuDNN libraries that come with torch visible to ctranslate2.

    faster-whisper needs cuBLAS + cuDNN 9. The GPU build of torch ships them, so we
    load torch first (Linux: libraries become resolvable by soname; Windows: add the
    DLL folder). Returns True when a CUDA device is usable.
    """
    if torch_device() != "cuda":
        return False
    try:
        import torch

        torch.cuda.init()
        if sys.platform == "win32":
            lib = os.path.join(os.path.dirname(torch.__file__), "lib")
            if os.path.isdir(lib):
                os.add_dll_directory(lib)
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False
