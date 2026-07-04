from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import psutil


@dataclass(slots=True)
class GPU:
    name: str
    memory_bytes: int | None
    backend: str


@lru_cache(maxsize=1)
def _windows_gpus() -> tuple[GPU, ...]:
    if os.name != "nt":
        return ()
    script = (
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,AdapterRAM | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=2.5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=True,
        )
        payload = json.loads(result.stdout or "[]")
        items = payload if isinstance(payload, list) else [payload]
        gpus = []
        for item in items:
            name = item.get("Name") or "Unknown GPU"
            backend = "cuda" if "NVIDIA" in name.upper() else "vulkan"
            gpus.append(GPU(name=name, memory_bytes=item.get("AdapterRAM"), backend=backend))
        return tuple(gpus)
    except (OSError, ValueError, subprocess.SubprocessError):
        return ()


def hardware_assessment(storage_path: Path) -> dict[str, Any]:
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage(storage_path)
    gpus = list(_windows_gpus())
    usable_memory = max([gpu.memory_bytes or 0 for gpu in gpus] + [int(memory.total * 0.65)])
    gib = 1024**3
    if usable_memory >= 24 * gib:
        profile = "highest_quality"
        parameter_range = "14B–32B quantized"
        context = 8192
    elif usable_memory >= 10 * gib:
        profile = "balanced"
        parameter_range = "7B–14B quantized"
        context = 4096
    else:
        profile = "small_fast"
        parameter_range = "1B–4B quantized"
        context = 4096
    return {
        "os": platform.platform(),
        "architecture": platform.machine(),
        "cpu": platform.processor() or "Unknown CPU",
        "cpu_logical_cores": psutil.cpu_count(logical=True),
        "ram_total_bytes": memory.total,
        "ram_available_bytes": memory.available,
        "gpus": [asdict(gpu) for gpu in gpus],
        "disk_free_bytes": disk.free,
        "disk_total_bytes": disk.total,
        "recommended_profile": profile,
        "recommended_parameter_range": parameter_range,
        "recommended_context": context,
        "plain_summary": (
            f"This PC is best suited to {parameter_range} models with about "
            f"{context:,} tokens of working context. Larger contexts are available but slower."
        ),
    }


def resource_snapshot(models_dir: Path) -> dict[str, Any]:
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage(models_dir)
    model_files = [
        {"name": item.name, "size_bytes": item.stat().st_size}
        for item in sorted(models_dir.glob("*.gguf"))
    ]
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.05),
        "ram_percent": memory.percent,
        "ram_used_bytes": memory.used,
        "ram_total_bytes": memory.total,
        "disk_free_bytes": disk.free,
        "models_size_bytes": sum(item["size_bytes"] for item in model_files),
        "models": model_files,
    }
