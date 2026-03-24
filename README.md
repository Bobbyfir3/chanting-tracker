# Chanting Tracker

Simple Streamlit app for daily Buddhist and spiritual chanting practice.

## What It Does

- Add chant log entries day by day
- Choose from a chant dropdown
- Add new chant items later inside the app
- Upload one photo for your altar or deity image
- Track count or repetitions
- Track optional duration in minutes
- Save optional notes
- View history
- View summary by chant
- View monthly summary
- See total practice days and a simple streak count

## File Structure

```text
chanting/
  app.py
  requirements.txt
  supabase_schema.sql
  chanting_tracker.xlsx
  data/
    chants.json
    chant_logs.csv
    settings.json
```

## Local Setup

1. Open a terminal in `C:\Users\Sihan\BobbyCodex\chanting`
2. Create a virtual environment:

```powershell
python -m venv .venv
```

3. Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

4. Install dependencies:

```powershell
pip install -r requirements.txt
```

5. Run the app:

```powershell
streamlit run app.py
```

6. Streamlit will open a local URL in your browser, usually:

```text
http://localhost:8501
```

## How To Add New Chants Later

You have two options:

1. Use the sidebar in the app and click `Add Chant Item`
2. Edit `data/chants.json` directly and add a new chant name to the list

## Data Storage

- `data/chants.json` stores your chant list
- `data/chant_logs.csv` stores your daily log history
- `data/settings.json` stores the single uploaded photo
- Everything stays local on your computer

## Temporary Sharing

The fastest way to let someone else test your local app is a temporary tunnel.

1. Start the app locally:

```powershell
streamlit run app.py
```

2. In a second terminal, run a tunnel such as Cloudflare Tunnel and share the generated public link.

If `cloudflared` is installed in the default location on Windows, you can use:

```powershell
.\start_temporary_share.ps1
```

To stop the tunnel later:

```powershell
.\stop_temporary_share.ps1
```

## Proper Hosting With Shared Data

For a real hosted version that both of you can use, configure Supabase and then deploy the app on Streamlit Community Cloud.

1. Create a Supabase project
2. Run the SQL in `supabase_schema.sql`
3. Add `SUPABASE_URL` and `SUPABASE_KEY` as Streamlit secrets
4. Deploy the app from a GitHub repo on Streamlit Community Cloud

Once those secrets are present, the app automatically switches from local files to shared cloud data.

## Notes

- The app creates the `data/` files automatically on first run
- The streak is a simple consecutive-day streak based on logged practice dates
- You can log different chants on the same day by adding multiple entries
- The hosted version should use Supabase instead of local CSV or JSON files
- Use `.streamlit/secrets.toml.example` as the template for local or hosted Supabase secrets
