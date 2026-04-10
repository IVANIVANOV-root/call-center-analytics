"""
Транскрибация через faster-whisper (192.168.28.47:8181) + разбивка на роли через LLM.
Pipeline:
  1. Whisper → сырой текст
  2. LLM (GigaChat или Ollama) → размеченный диалог Оператор/Клиент
"""
import os
import time
import uuid
import requests
import urllib3

urllib3.disable_warnings()

from config import (
    WHISPER_ASR_URL,
    GIGACHAT_AUTH_KEY, GIGACHAT_SCOPE, GIGACHAT_OAUTH_URL, GIGACHAT_BASE_URL, GIGACHAT_MODEL,
    OLLAMA_BASE_URL, OLLAMA_MODEL,
)

WHISPER_TIMEOUT = 300

# Кэш GigaChat токенов: { auth_key: {"token": ..., "expires_at": ...} }
_gc_token_cache: dict = {}

ROLE_SPLIT_SYSTEM = """Ты — помощник по обработке записей телефонных разговоров.
Тебе дан сырой транскрипт телефонного разговора в колл-центре.
Разметь диалог по ролям Оператор / Клиент.

Признаки оператора: отвечает на звонок, называет организацию, предлагает услуги, задаёт уточняющие вопросы.
Признаки клиента: инициирует звонок с запросом, называет себя, уточняет информацию.
Первым всегда говорит Оператор.

Формат каждой реплики:
Оператор: (текст реплики)
Клиент: (текст реплики)

Верни ТОЛЬКО размеченный диалог. Без пояснений, без markdown."""


def _get_gigachat_token(auth_key: str) -> str:
    cache = _gc_token_cache.get(auth_key, {})
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
    _gc_token_cache[auth_key] = {
        "token": data["access_token"],
        "expires_at": data.get("expires_at", 0) / 1000,
    }
    return _gc_token_cache[auth_key]["token"]


def _call_gigachat_llm(messages: list, auth_key: str) -> str:
    token = _get_gigachat_token(auth_key)
    resp = requests.post(
        f"{GIGACHAT_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "model": GIGACHAT_MODEL,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 4000,
        },
        verify=False, timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _call_ollama_llm(messages: list) -> str:
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
    return resp.json()["message"]["content"].strip()


def transcribe_audio(audio_path: str, whisper_prompt: str = None) -> str:
    """Отправляет аудио на Whisper, возвращает сырой текст."""
    name = os.path.basename(audio_path)
    print(f"[whisper] Sending: {name}", flush=True)

    ext = name.rsplit(".", 1)[-1].lower()
    mime = {
        "mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg",
        "m4a": "audio/mp4", "aac": "audio/aac", "flac": "audio/flac",
        "opus": "audio/ogg",
    }.get(ext, "audio/mpeg")

    params = {"task": "transcribe", "output": "json", "language": "ru"}
    if whisper_prompt:
        params["initial_prompt"] = whisper_prompt

    with open(audio_path, "rb") as f:
        resp = requests.post(
            WHISPER_ASR_URL,
            params=params,
            files={"audio_file": (name, f, mime)},
            timeout=WHISPER_TIMEOUT,
        )
    resp.raise_for_status()
    data = resp.json()
    text = (data.get("text") or data.get("transcription") or "").strip()
    if text and text == text.upper():
        text = text.lower().capitalize()
    print(f"[whisper] Done: {len(text)} chars", flush=True)
    return text


def split_roles(raw_text: str, gigachat_token: str = None) -> str:
    """Разбивает сырой текст на роли через LLM."""
    if not raw_text.strip():
        return raw_text

    messages = [
        {"role": "system", "content": ROLE_SPLIT_SYSTEM},
        {"role": "user", "content": f"Текст разговора:\n{raw_text}"},
    ]

    auth_key = gigachat_token or GIGACHAT_AUTH_KEY

    if auth_key:
        try:
            result = _call_gigachat_llm(messages, auth_key)
            print("[roles] Done via GigaChat", flush=True)
            return result
        except Exception as e:
            print(f"[roles] GigaChat failed ({e}), fallback Ollama", flush=True)

    result = _call_ollama_llm(messages)
    print("[roles] Done via Ollama", flush=True)
    return result


def get_audio_duration(audio_path: str) -> int | None:
    """Возвращает длительность аудио в секундах. mutagen → ffprobe fallback."""
    try:
        from mutagen import File as MutagenFile
        audio = MutagenFile(audio_path)
        if audio and audio.info:
            return int(audio.info.length)
    except Exception:
        pass
    # Fallback: ffprobe (ffmpeg уже в контейнере)
    try:
        import subprocess, json
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", audio_path],
            capture_output=True, text=True, timeout=15
        )
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if "duration" in stream:
                return int(float(stream["duration"]))
    except Exception:
        pass
    return None


def transcribe(audio_path: str, gigachat_token: str = None, whisper_prompt: str = None) -> tuple[str, list]:
    """
    Полный пайплайн: Whisper ASR → разбивка на роли через LLM.
    Возвращает (размеченный диалог Оператор/Клиент, [])
    """
    raw = transcribe_audio(audio_path, whisper_prompt=whisper_prompt)
    if not raw:
        return "", []
    result = split_roles(raw, gigachat_token)
    return result, []
