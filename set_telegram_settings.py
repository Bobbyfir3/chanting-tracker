from pathlib import Path

def write_settings():
    path = Path(__file__).resolve().parent / 'data' / 'settings.json'
    payload = {
        'photo_data_url': '',
        'telegram_token': '8661895845:AAHGUBSMaLkzO5TETRrG-0djiqtA1IyHx8E',
        'telegram_chat_id': '8661895845',
        'telegram_auto_send': False,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Wrote settings to', path)

if __name__ == '__main__':
    import json
    write_settings()
