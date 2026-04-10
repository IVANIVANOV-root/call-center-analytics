# Call Center Analytics / Анализ звонков колл-центра

**Live demo:** https://audioanalitika.ru

A full-stack web application for automated call center quality analysis. Upload audio recordings, transcribe them with Whisper (faster-whisper), analyze with a local LLM (Ollama) or Sber GigaChat, cross-reference against a price list, and get a structured quality report per call.

---

Веб-приложение для автоматизированного анализа качества работы колл-центра. Загружайте аудиозаписи звонков, получайте транскрибацию через Whisper, AI-анализ через Ollama или GigaChat, проверку соответствия прайс-листу и структурированные отчёты.

## Features / Возможности

- **Audio transcription** — faster-whisper ASR with speaker diarization
- **AI analysis** — call quality scoring, issue detection, compliance check
- **Price list validation** — checks if agents quote correct prices
- **Multi-user** — roles: `admin`, `manager`, `viewer`
- **Per-user GigaChat tokens** — flexible AI backend selection
- **Tags & filters** — categorize and search calls
- **Docker deploy** — single `docker-compose up`

## Tech Stack

- **Backend:** Python 3.11, Flask, SQLite
- **ASR:** faster-whisper (self-hosted)
- **AI:** Ollama (local LLM) / Sber GigaChat API
- **Frontend:** Jinja2 templates, plain JS

## Quick Start

```bash
# With Docker
docker-compose up -d

# Or manually
pip install -r requirements.txt
export WHISPER_ASR_URL=http://localhost:8181/asr
export OLLAMA_BASE_URL=http://localhost:11434
python app.py
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `WHISPER_ASR_URL` | faster-whisper ASR endpoint | `http://localhost:8181/asr` |
| `OLLAMA_BASE_URL` | Ollama API base URL | `http://localhost:11434` |
| `OLLAMA_MODEL` | Ollama model name | `OxW/Vikhr-Nemo-12B-Instruct-R-21-09-24:q4_k_m` |
| `GIGACHAT_AUTH_KEY` | Sber GigaChat API key (optional) | — |
| `AI_BACKEND` | `ollama` or `gigachat` | `ollama` |
| `PORT` | HTTP port | `3000` |

## Price List

Place your price list at `price/price.txt` (one item per line). The AI will cross-reference agent quotes against this file.
