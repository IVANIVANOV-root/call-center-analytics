"""
Парсинг прайс-листа из текстового файла.
Умная выборка релевантных услуг для промпта ИИ.
"""
import re
import os
from config import PRICE_FILE, PRICE_CONTEXT_LIMIT

# Кэш per-user: { user_id: [items] }  и  None-ключ для глобального
_price_cache: dict = {}


def _get_price_path(user_id=None) -> str:
    try:
        import db
        if user_id is not None:
            active = db.get_active_price_for_user(user_id)
            if active:
                price_dir = os.environ.get("PRICE_DIR", "/app/price")
                path = os.path.join(price_dir, active)
                if os.path.exists(path):
                    return path
    except Exception:
        pass
    return PRICE_FILE


def load_prices(user_id=None) -> list[dict]:
    global _price_cache
    if user_id in _price_cache:
        return _price_cache[user_id]

    price_file = _get_price_path(user_id)
    if not os.path.exists(price_file):
        print(f"[prices] File {price_file} not found")
        _price_cache[user_id] = []
        return _price_cache[user_id]

    items = []
    with open(price_file, encoding="utf-8") as f:
        text = f.read()

    lines = [l.strip() for l in text.splitlines()]
    lines = [l for l in lines if l]

    price_re = re.compile(r'\d[\d\s]*(?:руб\.?|перв\.|повт\.|\d{3,})')

    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r'^[\d]+$', line) or len(line) < 5:
            i += 1
            continue
        if line.endswith(':') or line in ('Специалист', 'Цена, руб.', 'Наименование процедуры', 'Стоимость, руб.', 'No'):
            i += 1
            continue

        price_str = ""
        name = line

        if '\t' in line:
            parts = line.split('\t')
            name = parts[0].strip()
            price_str = '\t'.join(parts[1:]).strip()
        elif price_re.search(line):
            m = price_re.search(line)
            name = line[:m.start()].strip()
            price_str = line[m.start():].strip()
        else:
            if i + 1 < len(lines) and price_re.search(lines[i + 1]):
                price_str = lines[i + 1].strip()
                i += 1

        name = name.strip('*').strip()
        if name and len(name) > 4:
            items.append({
                "name": name,
                "price": price_str or "—",
                "name_lower": name.lower()
            })
        i += 1

    _price_cache[user_id] = items
    print(f"[prices] Loaded {len(items)} items (user_id={user_id})")
    return _price_cache[user_id]


_KEYWORDS = [
    "гинеколог", "кардиолог", "дерматолог", "невролог", "эндокринолог",
    "терапевт", "гастроэнтеролог", "педиатр", "лор", "уролог", "хирург",
    "офтальмолог", "онколог", "ревматолог", "психотерапевт", "диетолог",
    "косметолог", "трихолог", "узи", "мрт", "кт", "рентген", "анализ",
    "процедур", "массаж", "физиотерапи", "инъекц", "капельниц", "вакцин",
    "маммолог", "аллерголог", "венеролог", "диагност", "сомнолог",
]


def invalidate_cache(user_id=None):
    global _price_cache
    _price_cache.pop(user_id, None)


def get_relevant_services(transcript: str, limit: int = None, user_id=None) -> list[dict]:
    if limit is None:
        limit = PRICE_CONTEXT_LIMIT
    prices = load_prices(user_id)
    if not prices:
        return []

    transcript_lower = transcript.lower()
    found_keywords = [kw for kw in _KEYWORDS if kw in transcript_lower]

    if not found_keywords:
        return prices[:limit]

    scored = []
    for item in prices:
        score = sum(1 for kw in found_keywords if kw in item["name_lower"])
        if score > 0:
            scored.append((score, item))

    scored.sort(key=lambda x: -x[0])
    result = [item for _, item in scored[:limit]]

    if len(result) < 10:
        extras = [p for p in prices if p not in result][:limit - len(result)]
        result.extend(extras)

    return result


def build_price_context(transcript: str, user_id=None) -> str:
    services = get_relevant_services(transcript, user_id=user_id)
    if not services:
        return ""
    lines = ["Актуальный прайс-лист (подборка релевантных услуг):"]
    for s in services:
        lines.append(f"  * {s['name']} — {s['price']}")
    return "\n".join(lines)
