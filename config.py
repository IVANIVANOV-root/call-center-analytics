"""Call Center Analyzer — конфигурация"""
import os

DATA_DIR   = os.environ.get("DATA_DIR",  "/app/data")
AUDIO_DIR  = os.environ.get("AUDIO_DIR", "/app/audio")
PRICE_FILE = os.environ.get("PRICE_FILE", "/app/price/price.txt")
DB_PATH    = os.path.join(DATA_DIR, "calls.db")

PORT = int(os.environ.get("PORT", 3000))

# ─── Whisper (faster-whisper ASR) ────────────────────────────────────────────
# Set WHISPER_ASR_URL env var to point to your faster-whisper server
WHISPER_ASR_URL = os.environ.get("WHISPER_ASR_URL", "http://localhost:8181/asr")

# ─── Sber GigaChat ────────────────────────────────────────────────────────────
# Глобальный ключ (fallback если у пользователя не задан персональный токен)
GIGACHAT_AUTH_KEY  = os.environ.get("GIGACHAT_AUTH_KEY", "")
GIGACHAT_SCOPE     = "GIGACHAT_API_PERS"
GIGACHAT_OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
GIGACHAT_BASE_URL  = "https://gigachat.devices.sberbank.ru/api/v1"
GIGACHAT_MODEL     = "GigaChat"

# ─── Ollama (локальный fallback) ──────────────────────────────────────────────
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.environ.get("OLLAMA_MODEL", "OxW/Vikhr-Nemo-12B-Instruct-R-21-09-24:q4_k_m")

# ─── По умолчанию Ollama, GigaChat активируется через персональный токен ──────
AI_BACKEND = os.environ.get("AI_BACKEND", "ollama")

PRICE_CONTEXT_LIMIT = 30
