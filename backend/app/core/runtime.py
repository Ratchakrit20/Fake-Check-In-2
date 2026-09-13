from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HardwareProfile:
    logical_cpus: int
    pair_workers: int
    opencv_threads: int
    device: str
    vram_gb: float
    embedding_batch_size: int


def detect_hardware(cpu_workers: int, opencv_threads: int, embedding_batch_size: int) -> HardwareProfile:
    """Choose conservative defaults that scale across CPU-only and CUDA machines."""
    logical_cpus = max(1, os.cpu_count() or 1)
    workers = cpu_workers or max(1, min(8, logical_cpus // 2))
    cv_threads = opencv_threads or max(1, logical_cpus // workers)
    device, vram_gb = "cpu", 0.0
    auto_batch = 2 if logical_cpus <= 4 else 4
    try:
        import torch

        torch.set_num_threads(max(1, logical_cpus - 1))
        if torch.cuda.is_available():
            device = "cuda"
            vram_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
            auto_batch = 4 if vram_gb < 4 else 8 if vram_gb < 8 else 16 if vram_gb < 16 else 32
            torch.backends.cudnn.benchmark = True
    except ImportError:
        pass
    return HardwareProfile(
        logical_cpus=logical_cpus,
        pair_workers=workers,
        opencv_threads=cv_threads,
        device=device,
        vram_gb=round(vram_gb, 2),
        embedding_batch_size=embedding_batch_size or auto_batch,
    )
