"""Фоновый процессор: сканирует аудиофайлы, запускает транскрибацию и анализ."""
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from config import AUDIO_DIR
from db import (upsert_call, set_status, save_transcript,
                save_analysis, set_error, get_pending_ids, get_call, get_user_by_id)
from transcriber import transcribe, get_audio_duration
from analyzer import analyze
from prices import build_price_context

AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac", ".opus"}

# 1 воркер — Tesla последовательно: Whisper → LLM, без конкуренции за GPU
_executor = ThreadPoolExecutor(max_workers=1)
_processing_lock = threading.Lock()
_active_ids: set = set()


def _parse_filename(filename: str) -> tuple:
    m = re.match(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", filename)
    if m:
        y, mo, d, h, mi, s = m.groups()
        return f"{d}.{mo}.{y}", f"{h}:{mi}:{s}"
    return None, None


def scan_audio_dir() -> list:
    if not os.path.exists(AUDIO_DIR):
        return []
    new_files = []
    for fname in sorted(os.listdir(AUDIO_DIR)):
        ext = os.path.splitext(fname)[1].lower()
        if ext not in AUDIO_EXTS:
            continue
        call_date, call_time = _parse_filename(fname)
        call_id = upsert_call(fname, call_date, call_time)
        row = get_call(call_id)
        if row and row["status"] == "pending":
            new_files.append(fname)
    return new_files


def _process_one(call_id: int):
    with _processing_lock:
        if call_id in _active_ids:
            return
        _active_ids.add(call_id)

    row = get_call(call_id)
    if not row:
        _active_ids.discard(call_id)
        return

    audio_path = os.path.join(AUDIO_DIR, row["filename"])
    if not os.path.exists(audio_path):
        set_error(call_id, f"Файл не найден: {audio_path}")
        _active_ids.discard(call_id)
        return

    # Получаем токен и user_id пользователя
    user_id = row.get("user_id")
    gigachat_token = None
    whisper_prompt = None
    if user_id:
        user = get_user_by_id(user_id)
        if user:
            gigachat_token = user.get("gigachat_token") or None
            whisper_prompt = user.get("whisper_prompt") or None

    try:
        # Проверка отмены перед стартом
        fresh = get_call(call_id)
        if fresh and fresh["status"] == "cancelled":
            _active_ids.discard(call_id)
            return

        # Длительность аудио
        duration = get_audio_duration(audio_path)
        if duration:
            from db import get_conn
            with get_conn() as conn:
                conn.execute("UPDATE calls SET duration=? WHERE id=?", (duration, call_id))
                conn.commit()

        set_status(call_id, "transcribing")
        transcript, _ = transcribe(audio_path, gigachat_token=gigachat_token, whisper_prompt=whisper_prompt)
        save_transcript(call_id, transcript)

        # Проверка отмены после транскрибации
        if get_call(call_id)["status"] == "cancelled":
            _active_ids.discard(call_id)
            return

        set_status(call_id, "analyzing")
        price_context = build_price_context(transcript, user_id=user_id)
        result = analyze(transcript, price_context, gigachat_token=gigachat_token, user_id=user_id)
        save_analysis(call_id, result)

        # Автозаполнение оператора из анализа если не задан вручную
        if not row.get("operator") and result.get("operator_name"):
            from db import update_call_operator
            update_call_operator(call_id, result["operator_name"])

        print(f"[processor] #{call_id} {row['filename']} -> {result.get('result')} score={result.get('score')}", flush=True)

    except Exception as e:
        print(f"[processor] #{call_id} ERROR: {e}", flush=True)
        set_error(call_id, str(e))
    finally:
        _active_ids.discard(call_id)


def process_pending():
    ids = get_pending_ids()
    if not ids:
        return 0
    for call_id in ids:
        _executor.submit(_process_one, call_id)
    return len(ids)


def scan_and_process() -> int:
    scan_audio_dir()
    return process_pending()


def get_active_count() -> int:
    return len(_active_ids)
