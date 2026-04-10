"""
ИИ-анализ транскрипции разговора.
Использует персональный GigaChat-Lite токен пользователя или Ollama как fallback.
"""
import time
import uuid
import json
import requests
import urllib3
from config import (
    GIGACHAT_AUTH_KEY, GIGACHAT_SCOPE, GIGACHAT_OAUTH_URL, GIGACHAT_BASE_URL, GIGACHAT_MODEL,
    OLLAMA_BASE_URL, OLLAMA_MODEL,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Кэш токенов: { auth_key: {"token": ..., "expires_at": ...} }
_token_cache: dict = {}


def _get_gigachat_token(auth_key: str) -> str:
    cache = _token_cache.get(auth_key, {})
    if cache.get("token") and time.time() < cache.get("expires_at", 0) - 60:
        return cache["token"]
    resp = requests.post(
        GIGACHAT_OAUTH_URL,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
            "Authorization": f"Basic {auth_key}",
        },
        data={"scope": GIGACHAT_SCOPE},
        verify=False, timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache[auth_key] = {
        "token": data["access_token"],
        "expires_at": data.get("expires_at", 0) / 1000,
    }
    return _token_cache[auth_key]["token"]


def _call_llm(messages: list, gigachat_token: str = None) -> str:
    """Вызывает LLM: GigaChat-Lite (персональный → глобальный) или Ollama."""
    auth_key = gigachat_token or GIGACHAT_AUTH_KEY

    if auth_key:
        try:
            token = _get_gigachat_token(auth_key)
            resp = requests.post(
                f"{GIGACHAT_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "model": GIGACHAT_MODEL,
                    "messages": messages,
                    "temperature": 0.1,
                    "max_tokens": 2000,
                },
                verify=False, timeout=60,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[analyze] GigaChat failed ({e}), fallback Ollama", flush=True)

    # Ollama fallback
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.1},
        },
        timeout=600,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


DEFAULT_SYSTEM_PROMPT = """Ты — эксперт по качеству обслуживания клиентов с международным опытом в контакт-центрах.
Анализируй расшифровки телефонных переговоров и оценивай работу операторов.

Транскрипт уже размечен по ролям (Оператор / Клиент).

СТАНДАРТЫ ОЦЕНКИ — мировые практики Customer Experience:
- Активное слушание и эмпатия к клиенту
- Чёткость и полнота предоставляемой информации
- Профессионализм речи, отсутствие слов-паразитов
- Скорость и эффективность решения запроса
- Вежливость, позитивный тон на протяжении всего разговора
- Корректность информации о ценах и услугах (сверяй с прайсом если есть)
- Инициативность: предложение альтернатив, уточнение потребностей клиента

ВОЗМОЖНЫЕ РЕЗУЛЬТАТЫ РАЗГОВОРА (выбери один):
- записан — клиент записан, оформлен, назначена встреча или подтверждено целевое действие
- не записан — диалог о записи/оформлении был, но клиент не завершил целевое действие
- недозвон — не удалось соединиться, клиент не ответил или сбросил
- перезвон — договорились о повторном звонке, вопрос не решён сейчас
- справка — информационный звонок, клиент уточнял информацию без намерения совершить целевое действие
- прочее — внутренний звонок между сотрудниками, технический, нерелевантный или неопределяемый

Правила анализа:
1. Выбери итог строго из списка выше
2. Если оператор говорит что услуги нет — сверь с прайсом. Если услуга есть — это ОШИБКА
3. Если оператор называет неверную цену — это ОШИБКА
4. Оцени работу оператора по мировым стандартам Customer Experience
5. Дай конкретные, практичные рекомендации по улучшению конкретно этого разговора
6. Отвечай ТОЛЬКО JSON без markdown и пояснений
7. ВАЖНО — артефакты транскрибации: система распознавания речи Whisper может искажать собственные имена, названия препаратов, медицинские и специализированные термины. Если в тексте встречается слово, которое похоже на искажённое название препарата или термина — НЕ считай это ошибкой оператора. На аудиозаписи оператор мог произнести правильно, а Whisper транскрибировал с ошибкой. Засчитывай ошибку оператора только по однозначно неверному поведению, а не по предполагаемым искажениям распознавания."""

ANALYSIS_SCHEMA = {
    "result": "одно из: записан / не записан / недозвон / перезвон / справка / прочее",
    "service": "запрашиваемая услуга, специалист или тема звонка, или null",
    "appointment_date": "дата и время записи если есть, иначе null",
    "operator_name": "имя оператора если он представился или его назвали, иначе null",
    "patient_name": "имя клиента если упомянуто, иначе null",
    "operator_errors": ["конкретные ошибки оператора, [] если ошибок нет"],
    "incorrect_service_info": "описание если оператор неверно информировал об услуге/цене, иначе null",
    "tone": "вежливый / нейтральный / грубый",
    "call_quality": "хорошее / удовлетворительное / плохое",
    "summary": "краткое резюме разговора в 2-3 предложениях",
    "recommendations": "конкретные рекомендации оператору для улучшения качества этого звонка",
    "score": "целое число от 1 до 10 — оценка работы оператора по мировым стандартам",
}


def _get_system_prompt(user_id=None) -> str:
    try:
        import db
        content = db.get_active_prompt_content(user_id)
        if content:
            return content
    except Exception:
        pass
    return DEFAULT_SYSTEM_PROMPT


def analyze(transcript: str, price_context: str = "", gigachat_token: str = None, user_id=None) -> dict:
    schema_str = json.dumps(ANALYSIS_SCHEMA, ensure_ascii=False, indent=2)
    price_block = f"\n\n{price_context}" if price_context else ""

    user_prompt = f"""{price_block}

РАСШИФРОВКА РАЗГОВОРА:
{transcript}

Верни JSON строго по схеме:
{schema_str}"""

    system_prompt = _get_system_prompt(user_id)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt},
    ]
    backend = "GigaChat-Lite" if (gigachat_token or GIGACHAT_AUTH_KEY) else "Ollama"
    print(f"[analyze] backend={backend}", flush=True)
    raw = _call_llm(messages, gigachat_token)
    return _parse_json(raw)


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if "<think>" in raw:
        end = raw.find("</think>")
        if end != -1:
            raw = raw[end + 8:].strip()

    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            if part.startswith("json"):
                part = part[4:]
            part = part.strip()
            if part.startswith("{"):
                raw = part
                break

    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]

    try:
        result = json.loads(raw)
        if "score" in result:
            try:
                result["score"] = int(result["score"])
            except (ValueError, TypeError):
                result["score"] = None
        if "operator_errors" in result and not isinstance(result["operator_errors"], list):
            errs = result["operator_errors"]
            result["operator_errors"] = [str(errs)] if errs else []
        return result
    except json.JSONDecodeError as e:
        print(f"[analyze] JSON parse error: {e}\nRaw: {raw[:300]}")
        return {
            "result": "прочее",
            "operator_errors": [],
            "summary": f"Ошибка парсинга ответа ИИ: {str(e)[:100]}",
            "score": None,
        }
