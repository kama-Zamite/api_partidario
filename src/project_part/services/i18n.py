# app/services/i18n.py
import json
from pathlib import Path
from functools import lru_cache

LOCALES_DIR = Path(__file__).parent.parent / "locales"

@lru_cache()
def load_translations(lang: str) -> dict:
    file_path = LOCALES_DIR / f"{lang}.json"
    if not file_path.exists():
        # Fallback para português
        file_path = LOCALES_DIR / "pt.json"
    with open(file_path, encoding="utf-8") as f:
        return json.load(f)

def translate(key: str, lang: str = "pt", **kwargs) -> str:
    translations = load_translations(lang)
    text = translations.get(key, key)  # se não encontrar, devolve a chave
    return text.format(**kwargs) if kwargs else text