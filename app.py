from __future__ import annotations

import base64
import csv
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

try:
    from supabase import Client, create_client
except ImportError:
    Client = None
    create_client = None


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CHANTS_FILE = DATA_DIR / "chants.json"
LOGS_FILE = DATA_DIR / "chant_logs.csv"
SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULT_CHANTS = [
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
    "不動明王 心咒",
    "真佛经",
    "蓮花童子心咒",
]

CSV_HEADERS = ["entry_id", "date", "chant_name", "count", "unit", "duration_minutes", "notes", "created_at"]


@dataclass
class ChantLog:
    entry_id: str
    date: str
    chant_name: str
    count: int
    unit: str
    duration_minutes: int
    notes: str
    created_at: str


def get_supabase_credentials() -> tuple[Optional[str], Optional[str]]:
    try:
        secrets = st.secrets
        secret_url = secrets.get("SUPABASE_URL")
        secret_key = secrets.get("SUPABASE_KEY")
    except StreamlitSecretNotFoundError:
        secret_url = None
        secret_key = None

    url = os.getenv("SUPABASE_URL") or secret_url
    key = os.getenv("SUPABASE_KEY") or secret_key
    return url, key


@st.cache_resource
def get_supabase_client() -> Optional[Client]:
    url, key = get_supabase_credentials()
    if not url or not key or create_client is None:
        return None
    return create_client(url, key)


def ensure_local_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not CHANTS_FILE.exists():
        CHANTS_FILE.write_text(
            json.dumps({"chants": DEFAULT_CHANTS}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if not LOGS_FILE.exists():
        with LOGS_FILE.open("w", newline="", encoding="utf-8-sig") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=CSV_HEADERS)
            writer.writeheader()

    if not SETTINGS_FILE.exists():
        SETTINGS_FILE.write_text(json.dumps({"photo_data_url": ""}, ensure_ascii=False, indent=2), encoding="utf-8")


def load_local_chants() -> List[str]:
    payload = json.loads(CHANTS_FILE.read_text(encoding="utf-8"))
    chants = payload.get("chants", [])
    return sorted({item.strip() for item in chants if item and item.strip()})


def save_local_chants(chants: List[str]) -> None:
    CHANTS_FILE.write_text(
        json.dumps({"chants": chants}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_local_logs() -> List[ChantLog]:
    with LOGS_FILE.open("r", newline="", encoding="utf-8-sig") as csvfile:
        reader = csv.DictReader(csvfile)
        rows = []
        for row in reader:
            rows.append(
                ChantLog(
                    entry_id=row["entry_id"],
                    date=row["date"],
                    chant_name=row["chant_name"],
                    count=int(row["count"] or 0),
                    unit=row["unit"],
                    duration_minutes=int(row["duration_minutes"] or 0),
                    notes=row["notes"],
                    created_at=row["created_at"],
                )
            )
    return rows


def save_local_log(log: ChantLog) -> None:
    with LOGS_FILE.open("a", newline="", encoding="utf-8-sig") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=CSV_HEADERS)
        writer.writerow(
            {
                "entry_id": log.entry_id,
                "date": log.date,
                "chant_name": log.chant_name,
                "count": log.count,
                "unit": log.unit,
                "duration_minutes": log.duration_minutes,
                "notes": log.notes,
                "created_at": log.created_at,
            }
        )


def load_local_settings() -> dict:
    return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))


def save_local_settings(settings: dict) -> None:
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_chants(chants: List[str]) -> List[str]:
    return sorted({item.strip() for item in chants if item and item.strip()})


def load_remote_chants(client: Client) -> List[str]:
    response = client.table("chants").select("name").order("name").execute()
    return [row["name"] for row in response.data or []]


def add_remote_chant(client: Client, chant_name: str) -> bool:
    existing = client.table("chants").select("name").eq("name", chant_name).execute()
    if existing.data:
        return False
    client.table("chants").insert({"name": chant_name}).execute()
    return True


def load_remote_logs(client: Client) -> List[ChantLog]:
    response = client.table("chant_logs").select("*").order("date", desc=True).order("created_at", desc=True).execute()
    logs = []
    for row in response.data or []:
        logs.append(
            ChantLog(
                entry_id=row["entry_id"],
                date=row["date"],
                chant_name=row["chant_name"],
                count=int(row.get("count") or 0),
                unit=row.get("unit") or "",
                duration_minutes=int(row.get("duration_minutes") or 0),
                notes=row.get("notes") or "",
                created_at=row.get("created_at") or "",
            )
        )
    return logs


def save_remote_log(client: Client, log: ChantLog) -> None:
    client.table("chant_logs").insert(
        {
            "entry_id": log.entry_id,
            "date": log.date,
            "chant_name": log.chant_name,
            "count": log.count,
            "unit": log.unit,
            "duration_minutes": log.duration_minutes,
            "notes": log.notes,
            "created_at": log.created_at,
        }
    ).execute()


def load_remote_settings(client: Client) -> dict:
    response = client.table("app_settings").select("key,value").execute()
    settings = {row["key"]: row["value"] for row in response.data or []}
    return {"photo_data_url": settings.get("photo_data_url", "")}


def save_remote_photo(client: Client, photo_data_url: str) -> None:
    existing = client.table("app_settings").select("key").eq("key", "photo_data_url").execute()
    payload = {"key": "photo_data_url", "value": photo_data_url}
    if existing.data:
        client.table("app_settings").update({"value": photo_data_url}).eq("key", "photo_data_url").execute()
    else:
        client.table("app_settings").insert(payload).execute()


class Storage:
    def __init__(self) -> None:
        self.client = get_supabase_client()
        if self.client is None:
            ensure_local_storage()

    @property
    def mode(self) -> str:
        return "supabase" if self.client is not None else "local"

    def load_chants(self) -> List[str]:
        if self.client is not None:
            chants = load_remote_chants(self.client)
            return normalize_chants(chants)
        return load_local_chants()

    def add_chant(self, new_chant: str) -> bool:
        chant_name = new_chant.strip()
        if not chant_name:
            return False

        if self.client is not None:
            return add_remote_chant(self.client, chant_name)

        chants = load_local_chants()
        if chant_name in chants:
            return False
        chants.append(chant_name)
        save_local_chants(normalize_chants(chants))
        return True

    def load_logs(self) -> List[ChantLog]:
        if self.client is not None:
            return load_remote_logs(self.client)
        return load_local_logs()

    def save_log(self, log: ChantLog) -> None:
        if self.client is not None:
            save_remote_log(self.client, log)
            return
        save_local_log(log)

    def load_settings(self) -> dict:
        if self.client is not None:
            return load_remote_settings(self.client)
        return load_local_settings()

    def save_photo(self, photo_data_url: str) -> None:
        if self.client is not None:
            save_remote_photo(self.client, photo_data_url)
            return
        settings = self.load_settings()
        settings["photo_data_url"] = photo_data_url
        save_local_settings(settings)


def parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def format_minutes(total_minutes: int) -> str:
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def decode_data_url_image(photo_data_url: str) -> Optional[bytes]:
    if not photo_data_url or not photo_data_url.startswith("data:"):
        return None

    try:
        _, encoded = photo_data_url.split(",", 1)
        return base64.b64decode(encoded)
    except (ValueError, base64.binascii.Error):
        return None


def compute_streak(days: List[date]) -> int:
    if not days:
        return 0

    streak = 0
    current = date.today()
    available = set(days)

    while current in available:
        streak += 1
        current -= timedelta(days=1)

    if streak == 0 and (date.today() - timedelta(days=1)) in available:
        current = date.today() - timedelta(days=1)
        while current in available:
            streak += 1
            current -= timedelta(days=1)

    return streak


def build_summary(logs: List[ChantLog]) -> Dict[str, object]:
    practice_days = sorted({parse_iso_date(log.date) for log in logs})
    total_minutes = sum(log.duration_minutes for log in logs)

    by_chant: Dict[str, Dict[str, int]] = defaultdict(lambda: {"entries": 0, "count": 0, "minutes": 0})
    by_month: Dict[str, Dict[str, int]] = defaultdict(lambda: {"entries": 0, "practice_days": 0, "count": 0, "minutes": 0})
    month_days: Dict[str, set] = defaultdict(set)

    for log in logs:
        month_key = log.date[:7]
        by_chant[log.chant_name]["entries"] += 1
        by_chant[log.chant_name]["count"] += log.count
        by_chant[log.chant_name]["minutes"] += log.duration_minutes
        by_month[month_key]["entries"] += 1
        by_month[month_key]["count"] += log.count
        by_month[month_key]["minutes"] += log.duration_minutes
        month_days[month_key].add(log.date)

    for month_key, days in month_days.items():
        by_month[month_key]["practice_days"] = len(days)

    return {
        "total_entries": len(logs),
        "total_practice_days": len(practice_days),
        "total_minutes": total_minutes,
        "current_streak": compute_streak(practice_days),
        "by_chant": dict(sorted(by_chant.items(), key=lambda item: (-item[1]["entries"], item[0]))),
        "by_month": dict(sorted(by_month.items(), reverse=True)),
    }


def render_metrics(summary: Dict[str, object]) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Practice Days", summary["total_practice_days"])
    col2.metric("Current Streak", summary["current_streak"])
    col3.metric("Total Entries", summary["total_entries"])
    col4.metric("Total Duration", format_minutes(int(summary["total_minutes"])))


def render_photo_section(storage: Storage, settings: dict) -> None:
    st.subheader("Sacred Photo")
    photo_data_url = settings.get("photo_data_url", "")
    photo_bytes = decode_data_url_image(photo_data_url)

    if photo_bytes:
        st.image(photo_bytes, use_container_width=True)
        if st.button("Remove Photo", use_container_width=True):
            storage.save_photo("")
            st.success("Photo removed.")
            st.rerun()
    else:
        st.info("Upload one photo to place your deity or altar image here.")

    uploaded_photo = st.file_uploader(
        "Upload one photo",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=False,
        help="This stores a single image for the app header area.",
    )
    if uploaded_photo is not None:
        mime_type = uploaded_photo.type or "image/png"
        encoded = base64.b64encode(uploaded_photo.getvalue()).decode("utf-8")
        photo_data_url = f"data:{mime_type};base64,{encoded}"
        storage.save_photo(photo_data_url)
        st.success("Photo saved.")
        st.rerun()


def render_history(logs: List[ChantLog]) -> None:
    st.subheader("History")
    if not logs:
        st.info("No chant logs yet. Add your first entry above.")
        return

    rows = [
        {
            "Date": log.date,
            "Chant": log.chant_name,
            "Count": log.count,
            "Unit": log.unit,
            "Duration (min)": log.duration_minutes or "",
            "Notes": log.notes,
        }
        for log in sorted(logs, key=lambda item: (item.date, item.created_at), reverse=True)
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_chant_summary(summary: Dict[str, object]) -> None:
    st.subheader("Summary By Chant")
    chant_summary = summary["by_chant"]
    if not chant_summary:
        st.info("Summary will appear after you add some logs.")
        return

    rows = [
        {
            "Chant": chant,
            "Entries": values["entries"],
            "Total Count": values["count"],
            "Total Duration": format_minutes(values["minutes"]),
        }
        for chant, values in chant_summary.items()
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_month_summary(summary: Dict[str, object]) -> None:
    st.subheader("Monthly Summary")
    month_summary = summary["by_month"]
    if not month_summary:
        st.info("Monthly summary will appear after you add some logs.")
        return

    rows = [
        {
            "Month": month,
            "Practice Days": values["practice_days"],
            "Entries": values["entries"],
            "Total Count": values["count"],
            "Total Duration": format_minutes(values["minutes"]),
        }
        for month, values in month_summary.items()
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def main() -> None:
    st.set_page_config(page_title="Chanting Tracker", page_icon="🪷", layout="wide")
    storage = Storage()
    chants = storage.load_chants()
    logs = storage.load_logs()
    settings = storage.load_settings()
    summary = build_summary(logs)

    st.title("Chanting Tracker")
    st.caption("Simple daily tracker for Buddhist and spiritual chanting practice.")

    with st.sidebar:
        st.header("Add New Chant")
        new_chant_name = st.text_input("Chant name", placeholder="例如：準提神咒")
        if st.button("Add Chant Item", use_container_width=True):
            if storage.add_chant(new_chant_name):
                st.success("Chant item added.")
                st.rerun()
            else:
                st.warning("Please enter a new chant name that is not already in the list.")

        st.divider()
        st.header("Storage Mode")
        st.write("Current mode:", storage.mode)
        if storage.mode == "local":
            st.caption("Using local files on this computer.")
            st.code(str(CHANTS_FILE), language=None)
            st.code(str(LOGS_FILE), language=None)
            st.code(str(SETTINGS_FILE), language=None)
        else:
            st.caption("Using shared Supabase data.")

    if not chants:
        st.error("No chant items found. Add one in data/chants.json or the database to get started.")
        st.stop()

    hero_col, metrics_col = st.columns([1, 2])
    with hero_col:
        render_photo_section(storage, settings)
    with metrics_col:
        render_metrics(summary)

    st.subheader("Add Chant Log Entry")
    with st.form("chant_log_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        selected_date = col1.date_input("Date", value=date.today())
        selected_chant = col2.selectbox("Chant", chants, index=0 if chants else None)

        col3, col4, col5 = st.columns(3)
        count = col3.number_input("Count / Repetitions", min_value=1, value=1, step=1)
        unit = col4.text_input("Unit", value="遍")
        duration_minutes = col5.number_input("Duration (minutes)", min_value=0, value=0, step=1)

        notes = st.text_area("Notes", placeholder="Optional notes for today")
        submitted = st.form_submit_button("Save Entry", use_container_width=True)

        if submitted:
            log = ChantLog(
                entry_id=datetime.now().strftime("%Y%m%d%H%M%S%f"),
                date=selected_date.isoformat(),
                chant_name=selected_chant,
                count=int(count),
                unit=unit.strip() or "遍",
                duration_minutes=int(duration_minutes),
                notes=notes.strip(),
                created_at=datetime.now().isoformat(timespec="seconds"),
            )
            storage.save_log(log)
            st.success("Chant log saved.")
            st.rerun()

    tab1, tab2, tab3 = st.tabs(["History", "By Chant", "By Month"])
    with tab1:
        render_history(logs)
    with tab2:
        render_chant_summary(summary)
    with tab3:
        render_month_summary(summary)


if __name__ == "__main__":
    main()
