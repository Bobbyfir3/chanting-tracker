from __future__ import annotations

import atexit
import csv
import json
import os
import re
import shutil
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

try:
	import tomllib
except ModuleNotFoundError:
	tomllib = None


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(
	os.getenv("CHANTING_DATA_DIR")
	or os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
	or str(BASE_DIR / "data")
).resolve()
SETTINGS_FILE = DATA_DIR / "settings.json"
LOGS_FILE = DATA_DIR / "chant_logs.csv"
CHANTS_FILE = DATA_DIR / "chants.json"
OFFSET_FILE = DATA_DIR / "telegram_offset.txt"
STATE_FILE = DATA_DIR / "telegram_state.json"
SECRETS_FILE = BASE_DIR / ".streamlit" / "secrets.toml"
LOCK_FILE = DATA_DIR / "telegram_bot.lock"
SEED_LOGS_FILE = BASE_DIR / "seed" / "chant_logs_seed.csv"

CSV_HEADERS = ["entry_id", "date", "chant_name", "count", "unit", "duration_minutes", "notes", "created_at"]

RITUAL_PACKAGES: Dict[str, List[Tuple[str, int]]] = {
	"1": [
		("真佛经", 1),
		("佛说安宅陀罗尼咒经", 1),
		("佛說摩利支天經", 1),
		("莲花童子心咒", 108),
	],
	"2": [
		("真佛经", 1),
		("佛說摩利支天經", 1),
		("往生咒", 21),
		("莲花童子心咒", 108),
	],
}

CHANT_ALIASES: Dict[str, str] = {
	"佛说安宅陀罗尼咒经": "佛說安宅陀羅尼咒經",
	"佛说摩利支天经": "佛說摩利支天經",
	"莲花童子心咒": "蓮花童子心咒",
}

PINNED_SUMMARY_CHANTS: List[str] = [
	"地藏菩薩本願經 卷上",
	"地藏菩薩本願經 卷中",
	"地藏菩薩本願經 卷下",
]

DEFAULT_CHANTS: List[str] = [
	"百字明咒",
	"彌勒菩薩心咒",
	"瑤池金母 心咒",
	"摩利支天菩薩 心咒",
	"佛說摩利支天經",
	"地藏菩薩本願經 卷上",
	"地藏菩薩本願經 卷中",
	"地藏菩薩本願經 卷下",
	"地藏王菩薩 心咒",
	"高王觀世音經",
	"觀世音菩薩普門品",
	"安土地真言",
	"佛说安宅陀罗尼咒",
	"不動明王 心咒",
	"真佛经",
	"佛说安宅陀罗尼咒经",
	"往生咒",
	"蓮花童子心咒",
]


def ensure_runtime_files() -> None:
	DATA_DIR.mkdir(parents=True, exist_ok=True)

	if not CHANTS_FILE.exists():
		CHANTS_FILE.write_text(json.dumps({"chants": DEFAULT_CHANTS}, ensure_ascii=False, indent=2), encoding="utf-8")
	else:
		try:
			payload = json.loads(CHANTS_FILE.read_text(encoding="utf-8-sig"))
		except json.JSONDecodeError:
			payload = {"chants": []}

		existing = payload.get("chants", [])
		if not isinstance(existing, list):
			existing = []

		normalized_existing = {str(item).strip() for item in existing if str(item).strip()}
		updated = list(existing)
		for chant in DEFAULT_CHANTS:
			if chant not in normalized_existing:
				updated.append(chant)

		if len(updated) != len(existing):
			CHANTS_FILE.write_text(json.dumps({"chants": updated}, ensure_ascii=False, indent=2), encoding="utf-8")

	if not SETTINGS_FILE.exists():
		SETTINGS_FILE.write_text(
			json.dumps({"photo_data_url": "", "telegram_token": "", "telegram_chat_id": "", "telegram_auto_send": False}, ensure_ascii=False, indent=2),
			encoding="utf-8",
		)

	if not STATE_FILE.exists():
		STATE_FILE.write_text(json.dumps({"pending": {}, "last_saved": {}, "custom_request": {}}, ensure_ascii=False, indent=2), encoding="utf-8")

	if not OFFSET_FILE.exists():
		OFFSET_FILE.write_text("0", encoding="utf-8")


def restore_seed_logs_if_needed() -> None:
	if not SEED_LOGS_FILE.exists():
		return

	if LOGS_FILE.exists() and LOGS_FILE.stat().st_size > 0:
		return

	shutil.copyfile(SEED_LOGS_FILE, LOGS_FILE)


def load_settings() -> dict:
	ensure_runtime_files()
	if not SETTINGS_FILE.exists():
		return {}
	return json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig"))


def load_streamlit_secrets() -> dict:
	if tomllib is None or not SECRETS_FILE.exists():
		return {}

	try:
		with SECRETS_FILE.open("rb") as handle:
			payload = tomllib.load(handle)
	except (OSError, tomllib.TOMLDecodeError):
		return {}

	return payload if isinstance(payload, dict) else {}


def get_openai_api_key() -> Tuple[str, Optional[str]]:
	env_key = os.getenv("OPENAI_API_KEY", "").strip()
	if env_key:
		return env_key, "environment"

	settings = load_settings()
	settings_key = str(settings.get("openai_api_key") or settings.get("OPENAI_API_KEY") or "").strip()
	if settings_key:
		return settings_key, str(SETTINGS_FILE)

	secrets = load_streamlit_secrets()
	secrets_key = str(secrets.get("OPENAI_API_KEY") or "").strip()
	if secrets_key:
		return secrets_key, str(SECRETS_FILE)

	return "", None


def load_chants() -> List[str]:
	if not CHANTS_FILE.exists():
		return []
	payload = json.loads(CHANTS_FILE.read_text(encoding="utf-8"))
	chants = payload.get("chants", [])
	return sorted({item.strip() for item in chants if item and item.strip()})


def load_logs() -> List[dict]:
	if not LOGS_FILE.exists():
		return []
	with LOGS_FILE.open("r", newline="", encoding="utf-8-sig") as csvfile:
		reader = csv.DictReader(csvfile)
		return list(reader)


def save_log(chant_name: str, count: int, source_note: str, log_date: Optional[str] = None) -> dict:
	DATA_DIR.mkdir(parents=True, exist_ok=True)
	if not LOGS_FILE.exists():
		with LOGS_FILE.open("w", newline="", encoding="utf-8-sig") as csvfile:
			writer = csv.DictWriter(csvfile, fieldnames=CSV_HEADERS)
			writer.writeheader()

	target_date = log_date or date.today().isoformat()
	now = datetime.now().isoformat(timespec="seconds")
	entry_id = datetime.now().strftime("%Y%m%d%H%M%S%f")

	record = {
		"entry_id": entry_id,
		"date": target_date,
		"chant_name": chant_name,
		"count": int(count),
		"unit": "遍",
		"duration_minutes": 0,
		"notes": source_note,
		"created_at": now,
	}

	with LOGS_FILE.open("a", newline="", encoding="utf-8-sig") as csvfile:
		writer = csv.DictWriter(csvfile, fieldnames=CSV_HEADERS)
		writer.writerow(record)

	return record


def delete_log_by_entry_id(entry_id: str) -> Optional[dict]:
	if not LOGS_FILE.exists():
		return None

	with LOGS_FILE.open("r", newline="", encoding="utf-8-sig") as csvfile:
		reader = csv.DictReader(csvfile)
		rows = list(reader)

	deleted: Optional[dict] = None
	kept_rows: List[dict] = []
	for row in rows:
		if deleted is None and row.get("entry_id") == entry_id:
			deleted = row
			continue
		kept_rows.append(row)

	if deleted is None:
		return None

	with LOGS_FILE.open("w", newline="", encoding="utf-8-sig") as csvfile:
		writer = csv.DictWriter(csvfile, fieldnames=CSV_HEADERS)
		writer.writeheader()
		writer.writerows(kept_rows)

	return deleted


def build_summary_text() -> str:
	logs = load_logs()
	if not logs:
		return "No chant logs found yet."

	totals: Dict[str, int] = {}
	for row in logs:
		name = (row.get("chant_name") or "").strip()
		if not name:
			continue
		totals[name] = totals.get(name, 0) + int(row.get("count") or 0)

	for chant_name in PINNED_SUMMARY_CHANTS:
		totals.setdefault(chant_name, 0)

	ordered = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
	lines = ["Summary by chant:"]
	for chant_name, total in ordered:
		lines.append(f"- {chant_name}: {total}遍")
	return "\n".join(lines)


def build_weekly_summary_text(days: int = 7) -> str:
	logs = load_logs()
	if not logs:
		return "No chant logs found yet."

	today = date.today()
	target_dates = [(today - timedelta(days=offset)).isoformat() for offset in range(days)]
	logs_by_day: Dict[str, Dict[str, object]] = {
		target_date: {"chants": {}, "added": 0, "deleted": 0, "net": 0}
		for target_date in target_dates
	}

	for row in logs:
		log_date = (row.get("date") or "").strip()
		if log_date not in logs_by_day:
			continue

		chant_name = (row.get("chant_name") or "").strip()
		if not chant_name:
			continue

		count = int(row.get("count") or 0)
		day_totals = logs_by_day[log_date]
		chants = day_totals["chants"]
		if not isinstance(chants, dict):
			chants = {}
			day_totals["chants"] = chants

		chants[chant_name] = int(chants.get(chant_name, 0)) + count
		day_totals["net"] = int(day_totals.get("net", 0)) + count
		if count >= 0:
			day_totals["added"] = int(day_totals.get("added", 0)) + count
		else:
			day_totals["deleted"] = int(day_totals.get("deleted", 0)) + abs(count)

	lines = [f"Past {days} days:"]
	for target_date in target_dates:
		weekday_label = datetime.strptime(target_date, "%Y-%m-%d").strftime("%a")
		lines.append(f"{weekday_label} {target_date}")
		day_totals = logs_by_day[target_date]
		chants = day_totals.get("chants", {})
		if not chants:
			lines.append("No logs")
			lines.append("")
			continue

		added = int(day_totals.get("added", 0))
		deleted = int(day_totals.get("deleted", 0))
		net = int(day_totals.get("net", 0))
		lines.append(f"Added +{added}遍 | Deleted -{deleted}遍 | Net {net}遍")
		ordered = sorted(chants.items(), key=lambda item: (-item[1], item[0]))
		for chant_name, total in ordered:
			lines.append(f"{chant_name} {total}遍")
		lines.append("")

	return "\n".join(lines).strip()


def build_period_summary_text(period: str) -> str:
	logs = load_logs()
	if not logs:
		return "No chant logs found yet."

	today = date.today()
	if period == "month":
		label = today.strftime("%Y-%m")
		filtered = [row for row in logs if (row.get("date") or "").strip().startswith(f"{label}-")]
		title = f"This month ({label})"
	elif period == "year":
		label = today.strftime("%Y")
		filtered = [row for row in logs if (row.get("date") or "").strip().startswith(f"{label}-")]
		title = f"This year ({label})"
	else:
		return "Invalid period."

	totals: Dict[str, int] = {}
	for row in filtered:
		chant_name = (row.get("chant_name") or "").strip()
		if not chant_name:
			continue
		totals[chant_name] = totals.get(chant_name, 0) + int(row.get("count") or 0)

	for chant_name in PINNED_SUMMARY_CHANTS:
		totals.setdefault(chant_name, 0)

	ordered = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
	lines = [f"{title} summary:"]
	for chant_name, total in ordered:
		lines.append(f"- {chant_name}: {total}遍")
	if not filtered:
		lines.append("(No logs for this period yet.)")
	return "\n".join(lines)


def pick_chant_name(raw_name: str, chant_list: List[str]) -> Optional[str]:
	clean = raw_name.strip()
	if not clean:
		return None

	def normalize_name(value: str) -> str:
		return re.sub(r"\s+", "", value).strip()

	normalized_clean = normalize_name(clean)
	for chant in chant_list:
		if clean == chant:
			return chant
		if normalized_clean and normalize_name(chant) == normalized_clean:
			return chant

	candidates = [chant for chant in chant_list if chant in clean or clean in chant]
	if not candidates and normalized_clean:
		candidates = [
			chant
			for chant in chant_list
			if normalize_name(chant) in normalized_clean or normalized_clean in normalize_name(chant)
		]
	if not candidates:
		return None
	return sorted(candidates, key=len, reverse=True)[0]


def resolve_package_chant_name(raw_name: str, chant_list: List[str]) -> str:
	clean = raw_name.strip()
	if not clean:
		return raw_name

	matched = pick_chant_name(clean, chant_list)
	if matched:
		return matched

	alias = CHANT_ALIASES.get(clean)
	if alias:
		alias_match = pick_chant_name(alias, chant_list)
		if alias_match:
			return alias_match
	return clean


def apply_ritual_package(package_key: str, chant_list: List[str], source_note: str, multiplier: int = 1) -> List[dict]:
	package = RITUAL_PACKAGES.get(package_key)
	if not package:
		return []

	records: List[dict] = []
	for raw_name, base_count in package:
		chant_name = resolve_package_chant_name(raw_name, chant_list)
		record = save_log(chant_name, base_count * multiplier, source_note)
		records.append(record)
	return records


def parse_package_command(compact_cmd: str) -> Optional[Tuple[str, int, str]]:
	# Support natural variants for package add/reverse commands.
	add_match = re.fullmatch(
		r"(?:/?\+\s*|/?add\s*|/?log\s*|/?)(morning|night)",
		compact_cmd,
	)
	if add_match:
		period = add_match.group(1)
		package_key = "1" if period == "morning" else "2"
		return package_key, 1, f"telegram-package:+{period}"

	reverse_match = re.fullmatch(
		r"(?:/?(?:delete|remove|reverse|undo)\s+|/?-\s*)(morning|night)",
		compact_cmd,
	)
	if reverse_match:
		period = reverse_match.group(1)
		package_key = "1" if period == "morning" else "2"
		return package_key, -1, f"telegram-package:delete-{period}"

	return None


def parse_log_text(text: str, chant_list: List[str]) -> Optional[dict]:
	content = text.strip()
	if not content:
		return None

	if content.lower().startswith("chant "):
		content = content[6:].strip()
	if content.lower().startswith("log "):
		content = content[4:].strip()
	if content.lower().startswith("/log "):
		content = content[5:].strip()

	date_match = re.search(r"(\d{4}-\d{2}-\d{2})", content)
	log_date = date_match.group(1) if date_match else None
	if log_date:
		content = content.replace(log_date, " ").strip()

	raw_name: Optional[str] = None
	count: Optional[int] = None

	match = re.search(r"(.+?)\s*[xX×]\s*([\d,]+)$", content)
	if match:
		raw_name = match.group(1).strip(" -")
		count = int(match.group(2).replace(",", ""))
	else:
		match = re.search(r"(.+?)\s+([\d,]+)$", content)
		if match:
			raw_name = match.group(1).strip(" -")
			count = int(match.group(2).replace(",", ""))
		else:
			match = re.search(r"^([\d,]+)\s+(.+)$", content)
			if match:
				count = int(match.group(1).replace(",", ""))
				raw_name = match.group(2).strip(" -")

	if not raw_name or count is None:
		return None

	chant_name = pick_chant_name(raw_name, chant_list)
	if not chant_name:
		return None

	return {"chant_name": chant_name, "count": count, "date": log_date}


def telegram_api(token: str, method: str, payload: Optional[dict] = None, timeout: int = 30) -> dict:
	url = f"https://api.telegram.org/bot{token}/{method}"
	response = requests.post(url, data=payload or {}, timeout=timeout)
	response.raise_for_status()
	return response.json()


def register_commands(token: str) -> None:
	commands = [
		{"command": "start", "description": "Show start menu"},
		{"command": "myid", "description": "Show this chat ID"},
		{"command": "morning", "description": "Add morning ritual package"},
		{"command": "night", "description": "Add night ritual package"},
		{"command": "reverse", "description": "Reverse package: /reverse morning or /reverse night"},
		{"command": "summary", "description": "Show chant totals"},
		{"command": "week", "description": "Show past 7 days"},
		{"command": "month", "description": "Show this month totals"},
		{"command": "year", "description": "Show this year totals"},
		{"command": "chants", "description": "Pick chant button"},
		{"command": "delete", "description": "Delete last or by entry_id"},
	]
	telegram_api(token, "setMyCommands", {"commands": json.dumps(commands, ensure_ascii=False)}, timeout=30)


def ensure_polling_mode(token: str) -> None:
	# Clear webhook mode so getUpdates polling can run without API conflicts.
	telegram_api(token, "deleteWebhook", {"drop_pending_updates": "false"}, timeout=30)


def telegram_get_file(token: str, file_id: str) -> Optional[bytes]:
	file_meta = telegram_api(token, "getFile", {"file_id": file_id})
	if not file_meta.get("ok"):
		return None
	file_path = file_meta.get("result", {}).get("file_path")
	if not file_path:
		return None

	url = f"https://api.telegram.org/file/bot{token}/{file_path}"
	response = requests.get(url, timeout=30)
	response.raise_for_status()
	return response.content


def transcribe_voice(audio_bytes: bytes) -> Tuple[Optional[str], Optional[str]]:
	api_key, source = get_openai_api_key()
	if not api_key:
		return None, "OPENAI_API_KEY is not configured."
	if api_key.startswith("YOUR_"):
		return None, f"OPENAI_API_KEY in {source or 'configuration'} is still a placeholder."

	headers = {"Authorization": f"Bearer {api_key}"}
	files = {"file": ("voice.ogg", audio_bytes, "audio/ogg")}
	data = {"model": "gpt-4o-mini-transcribe"}

	try:
		response = requests.post(
			"https://api.openai.com/v1/audio/transcriptions",
			headers=headers,
			data=data,
			files=files,
			timeout=60,
		)
	except requests.RequestException as exc:
		return None, f"Transcription request failed: {exc}"

	if response.status_code >= 400:
		details = response.text.strip().replace("\n", " ")
		return None, f"Transcription API error {response.status_code}: {details[:220]}"

	payload = response.json()
	text = (payload.get("text") or "").strip()
	if not text:
		return None, "Transcription returned empty text."
	return text, None


def send_message(token: str, chat_id: int, text: str) -> None:
	send_message_with_markup(token, chat_id, text)


def send_message_with_markup(token: str, chat_id: int, text: str, reply_markup: Optional[dict] = None) -> None:
	payload: dict = {"chat_id": str(chat_id), "text": text}
	if reply_markup is not None:
		payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
	telegram_api(token, "sendMessage", payload, timeout=30)


def answer_callback(token: str, callback_query_id: str, text: str = "") -> None:
	payload = {"callback_query_id": callback_query_id}
	if text:
		payload["text"] = text
	telegram_api(token, "answerCallbackQuery", payload, timeout=30)


def load_state() -> dict:
	if not STATE_FILE.exists():
		return {"pending": {}, "last_saved": {}, "custom_request": {}}
	try:
		state = json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))
		state.setdefault("pending", {})
		state.setdefault("last_saved", {})
		state.setdefault("custom_request", {})
		return state
	except json.JSONDecodeError:
		return {"pending": {}, "last_saved": {}, "custom_request": {}}


def save_state(state: dict) -> None:
	DATA_DIR.mkdir(parents=True, exist_ok=True)
	STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def set_pending_chant(chat_id: int, chant_name: str) -> None:
	state = load_state()
	pending = state.get("pending") or {}
	pending[str(chat_id)] = chant_name
	state["pending"] = pending
	save_state(state)


def pop_pending_chant(chat_id: int) -> Optional[str]:
	state = load_state()
	pending = state.get("pending") or {}
	key = str(chat_id)
	chant_name = pending.get(key)
	if chant_name:
		pending.pop(key, None)
		state["pending"] = pending
		save_state(state)
	return chant_name


def get_pending_chant(chat_id: int) -> Optional[str]:
	state = load_state()
	pending = state.get("pending") or {}
	return pending.get(str(chat_id))


def set_last_saved_entry(chat_id: int, entry_id: str) -> None:
	state = load_state()
	last_saved = state.get("last_saved") or {}
	last_saved[str(chat_id)] = entry_id
	state["last_saved"] = last_saved
	save_state(state)


def get_last_saved_entry(chat_id: int) -> Optional[str]:
	state = load_state()
	return (state.get("last_saved") or {}).get(str(chat_id))


def clear_last_saved_entry(chat_id: int) -> None:
	state = load_state()
	last_saved = state.get("last_saved") or {}
	last_saved.pop(str(chat_id), None)
	state["last_saved"] = last_saved
	save_state(state)


def set_custom_request_pending(chat_id: int, is_pending: bool) -> None:
	state = load_state()
	pending = state.get("custom_request") or {}
	key = str(chat_id)
	if is_pending:
		pending[key] = True
	else:
		pending.pop(key, None)
	state["custom_request"] = pending
	save_state(state)


def is_custom_request_pending(chat_id: int) -> bool:
	state = load_state()
	pending = state.get("custom_request") or {}
	return bool(pending.get(str(chat_id)))


def notify_owner_custom_request(token: str, requester_chat_id: int, requester_name: str, details: str = "") -> None:
	settings = load_settings()
	owner_chat_id = str(os.getenv("TELEGRAM_CHAT_ID") or settings.get("telegram_chat_id") or "").strip()
	if not owner_chat_id:
		return

	message = (
		"Custom chant request\n"
		f"From: {requester_name}\n"
		f"Chat ID: {requester_chat_id}"
	)
	if details:
		message += f"\nDetails: {details}"

	try:
		send_message(token, int(owner_chat_id), message)
	except Exception:
		return


def build_chant_keyboard(chant_list: List[str]) -> dict:
	rows: List[List[dict]] = []
	row: List[dict] = []
	for chant in chant_list:
		row.append({"text": chant, "callback_data": f"chant:{chant}"})
		if len(row) == 2:
			rows.append(row)
			row = []
	if row:
		rows.append(row)
	return {"inline_keyboard": rows}


def build_start_menu_text() -> str:
	return (
		"Welcome to your Chanting Assistant.\n\n"
		"Quick actions:\n"
		"1) Pick Chant and send count\n"
		"2) View Summary (Week/Month/Year)\n"
		"3) Quick log / Reverse custom group\n"
		"4) Request Custom Chant\n"
	)


def build_start_menu_keyboard() -> dict:
	return {
		"inline_keyboard": [
			[
				{"text": "Pick Chant", "callback_data": "menu:chants"},
				{"text": "Summary", "callback_data": "menu:summary"},
			],
			[
				{"text": "Past 7 Days", "callback_data": "menu:week"},
				{"text": "This Month", "callback_data": "menu:month"},
			],
			[
				{"text": "This Year", "callback_data": "menu:year"},
				{"text": "Request Custom Chant", "callback_data": "menu:request_custom"},
			],
			[
				{"text": "Morning (Custom)", "callback_data": "menu:add:1"},
				{"text": "Night (Custom)", "callback_data": "menu:add:2"},
			],
			[
				{"text": "Delete Morning", "callback_data": "menu:sub:1"},
				{"text": "Delete Night", "callback_data": "menu:sub:2"},
			],
		]
	}


def build_commands_text() -> str:
	return (
		"All commands:\n\n"
		"Summaries:\n"
		"- summary\n- week\n- month\n- year\n\n"
		"Ritual packages:\n"
		"- +morning, /morning, morning\n"
		"- +night, /night, night\n"
		"- Delete Morning / Reverse Morning\n"
		"- Delete Night / Reverse Night\n"
		"- /reverse morning\n- /reverse night\n\n"
		"Delete / undo:\n"
		"- /delete 不動明王心咒 7\n"
		"- /delete\n"
		"- /delete <entry_id>\n\n"
		"Picker:\n"
		"- /chants"
	)


def process_callback_query(token: str, callback_query: dict, chant_list: List[str]) -> None:
	callback_query_id = callback_query.get("id")
	data = callback_query.get("data") or ""
	message = callback_query.get("message") or {}
	chat_id = message.get("chat", {}).get("id")

	if not callback_query_id or not chat_id:
		return

	if data.startswith("chant:"):
		picked = data.split("chant:", 1)[1].strip()
		chant_name = pick_chant_name(picked, chant_list)
		if not chant_name:
			answer_callback(token, callback_query_id, "Chant not found")
			send_message(token, chat_id, "I could not match that chant. Please try again from the chant list.")
			return

		set_pending_chant(chat_id, chant_name)
		answer_callback(token, callback_query_id, "Selected")
		send_message(token, chat_id, f"Selected: {chant_name}\nNow send count only, e.g. 108")
		return

	if data == "menu:summary":
		answer_callback(token, callback_query_id, "Summary")
		send_message(token, chat_id, build_summary_text())
		return
	if data == "menu:week":
		answer_callback(token, callback_query_id, "Week")
		send_message(token, chat_id, build_weekly_summary_text())
		return
	if data == "menu:month":
		answer_callback(token, callback_query_id, "Month")
		send_message(token, chat_id, build_period_summary_text("month"))
		return
	if data == "menu:year":
		answer_callback(token, callback_query_id, "Year")
		send_message(token, chat_id, build_period_summary_text("year"))
		return
	if data == "menu:commands":
		answer_callback(token, callback_query_id, "Commands")
		send_message_with_markup(token, chat_id, build_commands_text(), build_start_menu_keyboard())
		return
	if data == "menu:chants":
		answer_callback(token, callback_query_id, "Pick chant")
		if not chant_list:
			send_message(token, chat_id, "No chants available yet.")
			return
		send_message_with_markup(token, chat_id, "Select one chant:", build_chant_keyboard(chant_list))
		return
	if data == "menu:request_custom":
		answer_callback(token, callback_query_id, "Request sent")
		set_custom_request_pending(chat_id, True)
		send_message(
			token,
			chat_id,
			"Send your custom chant request in this format:\n"
			"1) Chant name\n"
			"2) Optional note (why you need it)\n"
			"3) Grouping of various Chanting (if needed)\n\n"
			"Example:\n"
			"Chant: 佛說安宅陀羅尼咒經\n"
			"Grouping: Home Protection Set\n"
			"Include: 佛說安宅陀羅尼咒經, 往生咒, 蓮花童子心咒\n\n"
			"After you send it, I will forward to admin for manual update.",
		)
		return

	add_match = re.fullmatch(r"menu:add:([12])", data)
	if add_match:
		package_key = add_match.group(1)
		package_name = "Morning Chant Ritual" if package_key == "1" else "Night Chant Ritual"
		records = apply_ritual_package(package_key, chant_list, f"telegram-package:+{'morning' if package_key == '1' else 'night'}", multiplier=1)
		set_last_saved_entry(chat_id, records[-1]["entry_id"])
		lines = [f"Saved {package_name}:"]
		for item in records:
			lines.append(f"- {item['chant_name']} x {item['count']}遍")
		send_message_with_markup(token, chat_id, "\n".join(lines), build_start_menu_keyboard())
		answer_callback(token, callback_query_id, "Saved")
		return

	sub_match = re.fullmatch(r"menu:sub:([12])", data)
	if sub_match:
		package_key = sub_match.group(1)
		package_name = "Morning Chant Ritual" if package_key == "1" else "Night Chant Ritual"
		records = apply_ritual_package(package_key, chant_list, f"telegram-package:delete-{'morning' if package_key == '1' else 'night'}", multiplier=-1)
		set_last_saved_entry(chat_id, records[-1]["entry_id"])
		lines = [f"Applied reverse for {package_name}:"]
		for item in records:
			lines.append(f"- {item['chant_name']} x {item['count']}遍")
		send_message_with_markup(token, chat_id, "\n".join(lines), build_start_menu_keyboard())
		answer_callback(token, callback_query_id, "Reversed")
		return

	answer_callback(token, callback_query_id)


def load_offset() -> int:
	if not OFFSET_FILE.exists():
		return 0
	raw = OFFSET_FILE.read_text(encoding="utf-8").strip()
	if not raw.isdigit():
		return 0
	return int(raw)


def save_offset(offset: int) -> None:
	OFFSET_FILE.write_text(str(offset), encoding="utf-8")


def _is_pid_running(pid: int) -> bool:
	if pid <= 0:
		return False
	try:
		os.kill(pid, 0)
	except OSError:
		return False
	return True


def _is_bot_process(pid: int) -> bool:
	if pid <= 0:
		return False

	cmdline_path = Path(f"/proc/{pid}/cmdline")
	if not cmdline_path.exists():
		return False

	try:
		cmdline = cmdline_path.read_bytes().decode("utf-8", errors="ignore")
	except OSError:
		return False

	return "telegram_bot.py" in cmdline


def acquire_single_instance_lock() -> bool:
	DATA_DIR.mkdir(parents=True, exist_ok=True)

	if LOCK_FILE.exists():
		raw = LOCK_FILE.read_text(encoding="utf-8").strip()
		try:
			existing_pid = int(raw)
		except ValueError:
			existing_pid = 0

		if _is_pid_running(existing_pid) and _is_bot_process(existing_pid):
			if existing_pid != os.getpid():
				return False

		try:
			LOCK_FILE.unlink()
		except OSError:
			return False

	try:
		fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
		with os.fdopen(fd, "w", encoding="utf-8") as handle:
			handle.write(str(os.getpid()))
	except FileExistsError:
		return False

	return True


def release_single_instance_lock() -> None:
	if not LOCK_FILE.exists():
		return
	try:
		raw = LOCK_FILE.read_text(encoding="utf-8").strip()
		owner_pid = int(raw)
	except (OSError, ValueError):
		owner_pid = -1

	if owner_pid == os.getpid():
		try:
			LOCK_FILE.unlink()
		except OSError:
			pass


def process_message(token: str, message: dict, chant_list: List[str]) -> None:
	chat_id = message.get("chat", {}).get("id")
	if not chat_id:
		return

	text = (message.get("text") or "").strip()
	voice = message.get("voice")

	if text:
		cmd = text.lower()
		compact_cmd = re.sub(r"\s+", " ", cmd).strip()

		if cmd in {"/start", "help", "/help"}:
			send_message_with_markup(token, chat_id, build_start_menu_text(), build_start_menu_keyboard())
			return
		if cmd in {"/myid", "myid"}:
			send_message(token, chat_id, f"Your chat_id is: {chat_id}")
			return
		if cmd in {"summary", "/summary"}:
			send_message(token, chat_id, build_summary_text())
			return
		if cmd in {"week", "/week", "daily", "/daily"}:
			send_message(token, chat_id, build_weekly_summary_text())
			return
		if cmd in {"month", "/month", "monthly", "/monthly"}:
			send_message(token, chat_id, build_period_summary_text("month"))
			return
		if cmd in {"year", "/year", "yearly", "/yearly"}:
			send_message(token, chat_id, build_period_summary_text("year"))
			return

		if is_custom_request_pending(chat_id) and not text.startswith("/"):
			requester_name = (
				(message.get("from") or {}).get("first_name")
				or (message.get("from") or {}).get("username")
				or "Unknown"
			)
			notify_owner_custom_request(token, chat_id, requester_name, text)
			set_custom_request_pending(chat_id, False)
			send_message(token, chat_id, "Your custom chant request was sent. Admin will update it manually.")
			return

		package_command = parse_package_command(compact_cmd)
		if package_command:
			package_key, multiplier, source_note = package_command
			package_name = "Morning Chant Ritual" if package_key == "1" else "Night Chant Ritual"
			records = apply_ritual_package(package_key, chant_list, source_note, multiplier=multiplier)
			if not records:
				send_message(token, chat_id, "Package not found. Try /morning or /night.")
				return
			set_last_saved_entry(chat_id, records[-1]["entry_id"])
			header = f"Saved {package_name}:" if multiplier > 0 else f"Applied reverse for {package_name}:"
			lines = [header]
			for item in records:
				lines.append(f"- {item['chant_name']} x {item['count']}遍")
			send_message(token, chat_id, "\n".join(lines))
			return

		delete_minus_match = re.fullmatch(r"/delete\s+(.+?)\s+([\d,]+)", text, flags=re.IGNORECASE)
		if delete_minus_match:
			raw_name = delete_minus_match.group(1).strip()
			count = int(delete_minus_match.group(2).replace(",", ""))
			chant_name = pick_chant_name(raw_name, chant_list)
			if not chant_name:
				send_message(token, chat_id, "Chant not found. Please choose from the chant list.")
				return
			record = save_log(chant_name, -count, "telegram-delete-minus")
			set_last_saved_entry(chat_id, record["entry_id"])
			send_message(token, chat_id, f"Saved minus: {chant_name} x -{count}遍")
			return

		if cmd in {"delete", "/delete", "undo", "/undo"} or cmd.startswith("/delete ") or cmd.startswith("delete "):
			parts = text.split(maxsplit=1)
			explicit_entry_id = parts[1].strip() if len(parts) > 1 else ""
			target_entry_id = explicit_entry_id or get_last_saved_entry(chat_id)
			if not target_entry_id:
				send_message(token, chat_id, "No entry selected to delete. Use /delete <entry_id> or save a new entry first.")
				return
			deleted = delete_log_by_entry_id(target_entry_id)
			if not deleted:
				send_message(token, chat_id, "Entry not found. Please try again.")
				return
			if not explicit_entry_id:
				clear_last_saved_entry(chat_id)
			send_message(token, chat_id, f"Deleted: {deleted.get('chant_name', '')} x {deleted.get('count', '')}遍")
			return

		if cmd in {"/chants", "chants", "/", "/all"}:
			if not chant_list:
				send_message(token, chat_id, "No chants available yet.")
				return
			send_message_with_markup(token, chat_id, "Select one chant:", build_chant_keyboard(chant_list))
			return

		if text.startswith("/"):
			if not chant_list:
				send_message(token, chat_id, "No chants available yet.")
				return
			send_message_with_markup(token, chat_id, "Slash menu shortcut: select one chant:", build_chant_keyboard(chant_list))
			return

		pending_chant = get_pending_chant(chat_id)
		if pending_chant and re.fullmatch(r"[\d,]+", text):
			count = int(text.replace(",", ""))
			record = save_log(pending_chant, count, "telegram-select")
			pop_pending_chant(chat_id)
			set_last_saved_entry(chat_id, record["entry_id"])
			send_message(token, chat_id, f"Saved: {pending_chant} x {count}遍")
			return

		parsed = parse_log_text(text, chant_list)
		if not parsed:
			send_message(token, chat_id, "I could not understand that message. Please try again.")
			return

		record = save_log(parsed["chant_name"], parsed["count"], "telegram-text", parsed.get("date"))
		set_last_saved_entry(chat_id, record["entry_id"])
		send_message(token, chat_id, f"Saved: {parsed['chant_name']} x {parsed['count']}遍\nentry_id: {record['entry_id']}")
		return

	if voice:
		file_id = voice.get("file_id")
		if not file_id:
			send_message(token, chat_id, "Voice file missing. Please try again.")
			return

		audio_bytes = telegram_get_file(token, file_id)
		if not audio_bytes:
			send_message(token, chat_id, "Could not download voice message.")
			return

		transcript, transcribe_error = transcribe_voice(audio_bytes)
		if not transcript:
			send_message(token, chat_id, "Voice transcription is unavailable right now. Please send text instead.")
			return

		parsed = parse_log_text(transcript, chant_list)
		if not parsed:
			send_message(token, chat_id, "I could not understand the voice format. Please send as text with chant and count.")
			return

		record = save_log(parsed["chant_name"], parsed["count"], "telegram-voice", parsed.get("date"))
		set_last_saved_entry(chat_id, record["entry_id"])
		send_message(token, chat_id, f"Heard: {transcript}\nSaved: {parsed['chant_name']} x {parsed['count']}遍\nentry_id: {record['entry_id']}")


def run_bot() -> None:
	ensure_runtime_files()
	restore_seed_logs_if_needed()

	if not acquire_single_instance_lock():
		raise RuntimeError("Another telegram bot instance is already running.")

	atexit.register(release_single_instance_lock)

	settings = load_settings()
	token = str(os.getenv("TELEGRAM_TOKEN") or settings.get("telegram_token") or "").strip()
	if not token:
		raise RuntimeError("telegram_token missing. Set TELEGRAM_TOKEN env var or data/settings.json")

	try:
		register_commands(token)
	except Exception as exc:
		print(f"Could not register Telegram commands: {exc}")

	try:
		ensure_polling_mode(token)
	except Exception as exc:
		print(f"Could not switch Telegram to polling mode: {exc}")

	print("Telegram bot started. Press Ctrl+C to stop.")
	offset = load_offset()

	while True:
		try:
			result = telegram_api(token, "getUpdates", {"timeout": "30", "offset": str(offset)}, timeout=40)
			if not result.get("ok"):
				time.sleep(2)
				continue

			chant_list = load_chants()
			for update in result.get("result", []):
				update_id = int(update.get("update_id", 0))
				offset = update_id + 1
				save_offset(offset)

				callback_query = update.get("callback_query")
				if callback_query:
					process_callback_query(token, callback_query, chant_list)
					continue

				message = update.get("message") or {}
				process_message(token, message, chant_list)
		except KeyboardInterrupt:
			print("Stopped.")
			break
		except Exception as exc:
			print(f"Loop error: {exc}")
			time.sleep(2)

	release_single_instance_lock()


if __name__ == "__main__":
	run_bot()
