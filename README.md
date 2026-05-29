# JKK + UR Tracker

A background service that monitors Tokyo public housing vacancies from two sources:

- **JKK** (東京都住宅供給公社) — `to-kousya.or.jp`
- **UR Chintai** (都市再生機構) — `ur-net.co.jp`

The service scrapes both sites every 5 minutes, stores all listings in a local SQLite database, exports TSV spreadsheets, and generates an interactive map you can open in any browser.

---

## Features

- **Dual-source tracking** — JKK and UR listings in a single unified database
- **Change detection** — new listings, price changes, and vacancies that disappear are logged
- **Configurable filters** — ward, floor plan, rent range, floor level, building age
- **Room-level detail** — floor, area, rent, deposit, building age, access, equipment
- **Building detail URLs** — direct links to each building's page on the official website
- **GPS coordinates** — JKK buildings sourced from the JKK public API; UR addresses geocoded via the GSI API
- **Interactive HTML map** — Leaflet.js map with yellow bubbles (JKK) and red-purple bubbles (UR), clustering, hover popups, and source filters
- **TSV exports** — open in Excel / Numbers for filtering and sorting
- **macOS background service** — runs silently via launchd; survives logout/reboots

---

## Quick Start (Distribution Bundle)

> These steps are for recipients of `JKK_UR_Tracker_macOS.zip`.  
> Developers cloning the repo should see [Development Setup](#development-setup).

### 1. Unzip to a permanent location

```bash
unzip JKK_UR_Tracker_macOS.zip -d ~/Applications/
cd ~/Applications/JKK_UR_Tracker
```

### 2. Remove macOS quarantine

macOS will block unsigned binaries downloaded from the internet.

```bash
xattr -dr com.apple.quarantine ~/Applications/JKK_UR_Tracker
```

### 3. Edit `config.yaml`

Open `config.yaml` in any text editor and set your preferences:

```yaml
filters:
  wards: ["新宿区", "江東区"]          # Areas to track
  floor_plans: ["2LDK", "3LDK"]       # Room layouts
  rent_min: null                        # e.g. 80000
  rent_max: null                        # e.g. 150000
```

See [Configuration Reference](#configuration-reference) for all options.

### 4. Install and start the service

```bash
bash install_service.sh
```

The service starts immediately and runs every 5 minutes in the background.

### 5. Open the map

After the first scrape cycle (~2 minutes):

```bash
open data/map.html
```

Or open `data/map.html` directly in your browser.

---

## Output Files

All files are written to the `data/` directory:

| File | Description |
|---|---|
| `data/tracker.db` | SQLite database — all listings, change log, geocode cache |
| `data/listings_jkk.tsv` | JKK listings as tab-separated values |
| `data/listings_ur.tsv` | UR listings as tab-separated values |
| `data/listings_all.tsv` | All listings combined |
| `data/map.html` | Interactive Leaflet.js map (self-contained, works offline after load) |

---

## Map

`data/map.html` is a self-contained interactive map:

- 🟡 **Yellow circles** — JKK listings
- 🔴 **Red-purple circles** — UR listings
- Circle **size** scales with floor area (m²)
- **Hover** over a bubble to see listing details
- **Click** to pin the popup open
- Use the **filter panel** (top-right) to toggle sources or search by keyword
- Markers **cluster** at low zoom levels; click a cluster to expand it

The map requires an internet connection to load map tiles (OpenStreetMap).

---

## Service Management

| Task | Command |
|---|---|
| Start / reinstall | `bash install_service.sh` |
| Stop and remove | `bash uninstall_service.sh` |
| View live logs | `tail -f logs/jkk_tracker.log` |
| Reset all data | `bash clear_data.sh` |

Logs are written to:
- `logs/jkk_tracker.log` — structured application log
- `logs/stdout.log` / `logs/stderr.log` — raw process output

---

## Configuration Reference

`config.yaml` controls all runtime behaviour.

```yaml
check_interval_minutes: 5       # How often to scrape (minutes)

filters:
  wards: []                     # 区市名 list — empty = all wards
  floor_plans: []               # 間取り list — empty = all layouts
  rent_min: null                # Minimum monthly rent (¥)
  rent_max: null                # Maximum monthly rent (¥)
  area_min: null                # Minimum floor area (m²)
  area_max: null                # Maximum floor area (m²)
  building_age_max: null        # Max building age in years (JKK only)
  floor_min: null               # Minimum floor level
  floor_max: null               # Maximum floor level
  sources: []                   # ["JKK"], ["UR"], or [] for both

notifications:
  notify_all_changes: true      # Log every change
  notify_filtered_matches: true # Log matches against your filters

ur:
  enabled: true
  tdfk: "13"                    # Tokyo prefecture code (do not change)
  areas: ["01","02","03","04","05","06"]  # Tokyo area codes to scrape

transit:
  graph_refresh_days: 90        # Days before transit cache is rebuilt
```

---

## TSV Columns

Both JKK and UR exports share a common schema:

| Column | Description |
|---|---|
| `source` | `JKK` or `UR` |
| `listing_id` | Unique identifier |
| `building_name` | Building name (Japanese) |
| `ward` | Ward / city (区市) |
| `address` | Full address |
| `access` | Nearest station and walking time |
| `floor_plan` | Room layout (e.g. `2LDK`) |
| `area_sqm` | Floor area in m² |
| `floor` | Floor number |
| `building_floors` | Total floors in building |
| `rent_yen` | Monthly rent in ¥ |
| `deposit` | Deposit amount (¥ for JKK; months × rent for UR) |
| `building_age_years` | Building age in years |
| `unit_type` | Internal unit classification |
| `latitude` / `longitude` | GPS coordinates |
| `detail_url` | Direct link to building page |
| `first_seen` | Timestamp when first scraped |
| `last_seen` | Timestamp of most recent scrape |

---

## Development Setup

### Requirements

- macOS (Intel or Apple Silicon)
- Python 3.9+ (Homebrew recommended: `brew install python`)

### Install dependencies

```bash
pip3 install -r requirements.txt
```

### Run directly (without service)

```bash
python3 main.py
```

### Install as background service

```bash
bash install_service.sh
```

### Build the distribution bundle

```bash
bash build_dist.sh
```

Output: `dist/JKK_UR_Tracker_macOS.zip`  
Requires `pyinstaller` (`pip3 install pyinstaller`).

---

## Project Structure

```
JKK_UR_Tracker/
├── main.py                  # Entry point — orchestrates scraping cycles
├── config.yaml              # User configuration
├── requirements.txt         # Python dependencies
├── install_service.sh       # Install + start launchd agent
├── uninstall_service.sh     # Stop + remove launchd agent
├── clear_data.sh            # Reset all scraped data
├── build_dist.sh            # Build macOS distribution zip
├── JKK_UR_Tracker.spec      # PyInstaller spec
│
├── scraper/                 # Site-specific scrapers
│   ├── jkk_scraper.py       # JKK search + room-detail scraper
│   └── ur_scraper.py        # UR Chintai scraper
│
├── storage/                 # Persistence layer
│   ├── database.py          # SQLite schema, upsert, migration
│   ├── csv_export.py        # TSV export
│   ├── rooms_json.py        # JKK building metadata (rooms.json API)
│   ├── geocoder.py          # GSI API geocoding for UR addresses
│   └── map_export.py        # Leaflet.js HTML map generator
│
├── filters/                 # Listing filter logic
├── notifications/           # Change notification logic
├── scheduler/               # Interval scheduling
└── utils/                   # Shared utilities (paths, logging)
```

---

## Data Sources

| Source | URL | Update frequency |
|---|---|---|
| JKK vacancy search | `https://www.to-kousya.or.jp/chintai/` | Every 5 min |
| JKK building metadata | `https://www.to-kousya.or.jp/chintai/cms/json/rooms.json` | Cached 1 hour |
| UR Chintai search | `https://www.ur-net.co.jp/chintai/` | Every 5 min |
| Geocoding (UR) | `https://msearch.gsi.go.jp/address-search/` | Cached in DB |
| Map tiles | OpenStreetMap via unpkg CDN | On browser load |

---

## Notes

- The service only runs on **macOS** (uses launchd). Linux/Windows support would require a different service manager.
- GPS coordinates for JKK buildings come from JKK's own API and are 100% coverage. UR coordinates are resolved incrementally (10 per cycle) via the Japanese government's GSI geocoding API.
- The distribution binary is compiled for **Apple Silicon (arm64)**. It will not run on Intel Macs. Rebuild from source using `build_dist.sh` on an Intel Mac if needed.
- All scraped data remains **local** on your machine. No data is sent to any external service except geocoding requests (address strings only) to the Japanese government's GSI API.
