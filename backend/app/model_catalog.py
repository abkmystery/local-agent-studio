from __future__ import annotations


CATALOG = [
    {
        "id": "qwen2.5-0.5b-instruct-q4_k_m",
        "name": "Qwen 2.5 0.5B Quick Start",
        "profile": "small_fast",
        "description": "A sub-GB Apache-2.0 starter model for fast setup and basic agents on almost any supported PC.",
        "publisher": "Qwen",
        "repository": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        "filename": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "url": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "size_bytes": 491_000_000,
        "memory_estimate_bytes": 900_000_000,
        "context_length": 32768,
        "license_name": "Apache-2.0",
        "license_url": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/blob/main/LICENSE",
        "capabilities": ["chat", "structured_output"],
        "starter": True,
    },
    {
        "id": "qwen2.5-3b-instruct-q4_k_m",
        "name": "Qwen 2.5 3B Instruct",
        "profile": "small_fast",
        "description": "A compact Apache-2.0 model for lightweight agents and lower-memory PCs.",
        "publisher": "Qwen",
        "repository": "Qwen/Qwen2.5-3B-Instruct-GGUF",
        "filename": "qwen2.5-3b-instruct-q4_k_m.gguf",
        "url": "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf",
        "size_bytes": 2_100_000_000,
        "memory_estimate_bytes": 3_000_000_000,
        "context_length": 32768,
        "license_name": "Apache-2.0",
        "license_url": "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/blob/main/LICENSE",
        "capabilities": ["chat", "structured_output"],
    },
    {
        "id": "qwen2.5-7b-instruct-q4_k_m",
        "name": "Qwen 2.5 7B Instruct",
        "profile": "balanced",
        "description": "A balanced general-purpose Apache-2.0 model for agent workflows.",
        "publisher": "Qwen",
        "repository": "Qwen/Qwen2.5-7B-Instruct-GGUF",
        "filename": "qwen2.5-7b-instruct-q4_k_m.gguf",
        "url": "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/qwen2.5-7b-instruct-q4_k_m.gguf",
        "size_bytes": 4_700_000_000,
        "memory_estimate_bytes": 6_000_000_000,
        "context_length": 32768,
        "license_name": "Apache-2.0",
        "license_url": "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/blob/main/LICENSE",
        "capabilities": ["chat", "structured_output", "tool_use"],
    },
    {
        "id": "qwen2.5-14b-instruct-q4_k_m",
        "name": "Qwen 2.5 14B Instruct",
        "profile": "highest_quality",
        "description": "A larger Apache-2.0 model for stronger drafting and review on capable PCs.",
        "publisher": "Qwen",
        "repository": "Qwen/Qwen2.5-14B-Instruct-GGUF",
        "filename": "qwen2.5-14b-instruct-q4_k_m.gguf",
        "url": "https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF/resolve/main/qwen2.5-14b-instruct-q4_k_m.gguf",
        "size_bytes": 9_000_000_000,
        "memory_estimate_bytes": 11_000_000_000,
        "context_length": 32768,
        "license_name": "Apache-2.0",
        "license_url": "https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF/blob/main/LICENSE",
        "capabilities": ["chat", "structured_output", "tool_use"],
    },
]


def catalog_item(identifier: str) -> dict[str, object]:
    try:
        return next(item for item in CATALOG if item["id"] == identifier)
    except StopIteration as error:
        raise ValueError("Unknown curated model") from error
