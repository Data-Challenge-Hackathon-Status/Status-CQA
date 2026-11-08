"""Fetch the pinned text tokenizer only (11 MB), never model weights or generations."""
import hashlib
from pathlib import Path

import httpx

from .io import read_json


def main():
    receipt = read_json("config/tokenizer.qwen3.json")
    path = Path("data/tokenizers/qwen3-32b/tokenizer.json")
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != receipt["sha256"]:
            raise ValueError("Существующий токенизатор отличается; автоматическая замена запрещена")
        print("Токенизатор уже сохранён; SHA256 совпал.")
        return
    expected = "https://huggingface.co/Qwen/Qwen3-32B/resolve/" + receipt["revision"] + "/tokenizer.json"
    if receipt["url"] != expected:
        raise ValueError("Неожиданный источник токенизатора")
    with httpx.Client(timeout=60, trust_env=False, follow_redirects=True) as client:
        response = client.get(expected)
        response.raise_for_status()
    if hashlib.sha256(response.content).hexdigest() != receipt["sha256"] or len(response.content) != receipt["bytes"]:
        raise ValueError("Загрузка не совпала с зафиксированной контрольной суммой")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    print("Сохранён токенизатор; веса модели не загружались.")


if __name__ == "__main__":
    main()
