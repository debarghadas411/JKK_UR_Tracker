"""
Generate an interactive HTML map of all active JKK + UR listings using Leaflet.js.

The map is saved to  data/map.html  and is fully self-contained (CDN assets only).
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from utils.paths import DATA_DIR, PROJECT_ROOT

logger = logging.getLogger(__name__)

MAP_PATH      = DATA_DIR / "map.html"
DOCS_MAP_PATH = PROJECT_ROOT / "docs" / "index.html"

# Colour scheme
COLOR_JKK = "#FFD700"   # Yellow
COLOR_UR  = "#B5179E"   # Red-purple


def _listing_to_feature(listing: dict) -> Optional[dict]:
    """Convert a listing dict to a GeoJSON-like dict for the map."""
    lat = listing.get("latitude")
    lon = listing.get("longitude")
    if not lat or not lon:
        return None

    rent = listing.get("rent_yen") or 0
    mgmt = listing.get("management_fee_yen") or 0
    total = rent + mgmt

    detail_url = listing.get("detail_url") or ""
    detail_html = (
        f'<a href="{detail_url}" target="_blank" rel="noopener">View Detail ↗</a>'
        if detail_url else ""
    )

    deposit = listing.get("deposit_yen")
    deposit_str = f"¥{deposit:,}" if deposit else "—"

    area = listing.get("area_sqm")
    area_str = f"{area}㎡" if area else listing.get("area_text") or "—"

    available = listing.get("available_from") or "—"
    built = listing.get("built_year") or "—"

    return {
        "lat":    lat,
        "lon":    lon,
        "source": listing.get("source", "JKK"),
        "name":   listing.get("name", ""),
        "ward":   listing.get("ward", ""),
        "addr":   listing.get("address", ""),
        "plan":   listing.get("floor_plan", ""),
        "area":   area_str,
        "floor":  listing.get("floor") or "—",
        "rent":   f"¥{rent:,}" if rent else "—",
        "total":  f"¥{total:,}" if total else "—",
        "mgmt":   f"¥{mgmt:,}" if mgmt else "—",
        "dep":    deposit_str,
        "avail":  available,
        "built":  built,
        "access": listing.get("access") or "—",
        "url":    detail_url,
        "url_html": detail_html,
        "area_sqm": area or 0,
    }


def generate_map_html(listings: list[dict]) -> None:
    """Write MAP_PATH with an interactive Leaflet map of *listings*."""
    features = []
    for lst in listings:
        f = _listing_to_feature(lst)
        if f:
            features.append(f)

    jkk_count = sum(1 for f in features if f["source"] == "JKK")
    ur_count   = sum(1 for f in features if f["source"] == "UR")
    total_with_coords = len(features)
    total_listings = len(listings)

    listings_json = json.dumps(features, ensure_ascii=False)

    JST = timezone(timedelta(hours=9))
    updated_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JKK + UR Housing Map</title>

<!-- Leaflet 1.9.4 -->
<link  rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin=""/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>

<!-- Leaflet MarkerCluster 1.5.3 -->
<link  rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" crossorigin=""/>
<link  rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css" crossorigin=""/>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js" crossorigin=""></script>

<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body, #map {{ width: 100%; height: 100vh; font-family: sans-serif; }}

#control-panel {{
  position: absolute;
  top: 10px; right: 10px;
  z-index: 1000;
  background: white;
  border-radius: 10px;
  padding: 14px 16px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.25);
  min-width: 230px;
  max-width: 260px;
}}
#control-panel h2 {{
  font-size: 15px; font-weight: 700;
  margin-bottom: 10px; color: #1a1a2e;
  border-bottom: 2px solid #eee; padding-bottom: 6px;
}}
.filter-row {{
  display: flex; align-items: center; gap: 8px;
  margin: 6px 0;
}}
.dot {{
  width: 14px; height: 14px; border-radius: 50%;
  display: inline-block; border: 2px solid rgba(0,0,0,0.3);
  flex-shrink: 0;
}}
.dot-jkk {{ background: {COLOR_JKK}; }}
.dot-ur  {{ background: {COLOR_UR};  }}
.filter-row label {{ font-size: 13px; cursor: pointer; flex: 1; }}
.filter-row .count {{ font-size: 12px; color: #666; }}
#search-box {{
  width: 100%; margin-top: 10px;
  padding: 6px 8px; font-size: 13px;
  border: 1px solid #ccc; border-radius: 6px;
  outline: none;
}}
#search-box:focus {{ border-color: #4a90e2; }}
#stats {{
  margin-top: 10px; font-size: 12px; color: #555;
  border-top: 1px solid #eee; padding-top: 8px;
  line-height: 1.7;
}}
#stats b {{ color: #222; }}

.legend {{
  position: absolute;
  bottom: 30px; left: 10px;
  z-index: 1000;
  background: white;
  border-radius: 8px;
  padding: 10px 14px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.2);
  font-size: 12px;
}}
.legend h4 {{ margin-bottom: 6px; font-size: 13px; }}
.legend-row {{ display: flex; align-items: center; gap: 8px; margin: 4px 0; }}

/* Popup */
.popup-inner {{ min-width: 220px; max-width: 300px; }}
.popup-title {{ font-size: 14px; font-weight: 700; margin-bottom: 6px; }}
.popup-source {{
  display: inline-block; padding: 1px 7px;
  border-radius: 10px; font-size: 11px; font-weight: 600;
  margin-bottom: 8px;
}}
.popup-source-jkk {{ background: #FFF3CD; color: #856404; }}
.popup-source-ur  {{ background: #F3E6F8; color: #6f0080; }}
.popup-table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
.popup-table td {{ padding: 3px 4px; }}
.popup-table td:first-child {{ color: #666; width: 40%; white-space: nowrap; }}
.popup-table td:last-child  {{ font-weight: 500; }}
.popup-url {{ margin-top: 8px; text-align: right; font-size: 12px; }}
.popup-url a {{ color: #4a90e2; text-decoration: none; }}
.popup-url a:hover {{ text-decoration: underline; }}

/* Custom cluster colours */
.marker-cluster-jkk {{ background-color: rgba(255,215,0,0.5); }}
.marker-cluster-jkk div {{ background-color: rgba(255,215,0,0.8); color: #333; font-weight: 700; }}
.marker-cluster-ur  {{ background-color: rgba(181,23,158,0.35); }}
.marker-cluster-ur  div {{ background-color: rgba(181,23,158,0.7); color: #fff; font-weight: 700; }}
</style>
</head>
<body>
<div id="map"></div>

<div id="control-panel">
  <h2>🏠 JKK + UR Map</h2>
  <div class="filter-row">
    <input type="checkbox" id="chk-jkk" checked>
    <span class="dot dot-jkk"></span>
    <label for="chk-jkk">JKK</label>
    <span class="count" id="cnt-jkk">{jkk_count}</span>
  </div>
  <div class="filter-row">
    <input type="checkbox" id="chk-ur" checked>
    <span class="dot dot-ur"></span>
    <label for="chk-ur">UR</label>
    <span class="count" id="cnt-ur">{ur_count}</span>
  </div>
  <input id="search-box" type="text" placeholder="Search by name or ward…">
  <div id="stats">
    Showing <b id="stat-shown">{total_with_coords}</b> of <b>{total_listings}</b> listings
    ({total_listings - total_with_coords} without coordinates)<br>
    🕐 Updated: <b>{updated_str}</b>
  </div>
</div>

<div class="legend">
  <h4>Legend</h4>
  <div class="legend-row"><span class="dot dot-jkk"></span> JKK (Tokyo Kōsha)</div>
  <div class="legend-row"><span class="dot dot-ur"></span>  UR (Urban Renaissance)</div>
</div>

<script>
const LISTINGS = {listings_json};

const COLOR_JKK = "{COLOR_JKK}";
const COLOR_UR  = "{COLOR_UR}";

// Init map
const map = L.map('map', {{ zoomControl: true }});
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  maxZoom: 19,
}}).addTo(map);

// Cluster groups per source
const clusterJKK = L.markerClusterGroup({{
  iconCreateFunction: function(cluster) {{
    return L.divIcon({{
      html: '<div>' + cluster.getChildCount() + '</div>',
      className: 'marker-cluster marker-cluster-jkk',
      iconSize: [40, 40]
    }});
  }},
  maxClusterRadius: 60,
  showCoverageOnHover: false,
}});

const clusterUR = L.markerClusterGroup({{
  iconCreateFunction: function(cluster) {{
    return L.divIcon({{
      html: '<div>' + cluster.getChildCount() + '</div>',
      className: 'marker-cluster marker-cluster-ur',
      iconSize: [40, 40]
    }});
  }},
  maxClusterRadius: 60,
  showCoverageOnHover: false,
}});

// Build popup HTML
function buildPopup(f) {{
  const srcClass = f.source === 'JKK' ? 'popup-source-jkk' : 'popup-source-ur';
  const accessRow = f.access && f.access !== '—'
    ? `<tr><td>Access</td><td>${{f.access.replace(/<[^>]+>/g,' ').trim()}}</td></tr>` : '';
  const urlRow = f.url ? `<div class="popup-url">${{f.url_html}}</div>` : '';
  return `
    <div class="popup-inner">
      <div class="popup-title">${{escHtml(f.name)}}</div>
      <span class="popup-source ${{srcClass}}">${{f.source}}</span>
      <table class="popup-table">
        <tr><td>Ward</td><td>${{escHtml(f.ward)}}</td></tr>
        <tr><td>Address</td><td>${{escHtml(f.addr)}}</td></tr>
        <tr><td>Plan</td><td>${{escHtml(f.plan)}}</td></tr>
        <tr><td>Area</td><td>${{escHtml(f.area)}}</td></tr>
        <tr><td>Floor</td><td>${{f.floor}}</td></tr>
        <tr><td>Rent</td><td>${{f.rent}}</td></tr>
        <tr><td>Mgmt Fee</td><td>${{f.mgmt}}</td></tr>
        <tr><td>Total/mo</td><td><b>${{f.total}}</b></td></tr>
        <tr><td>Deposit</td><td>${{f.dep}}</td></tr>
        <tr><td>Available</td><td>${{escHtml(f.avail)}}</td></tr>
        <tr><td>Built</td><td>${{f.built}}</td></tr>
        ${{accessRow}}
      </table>
      ${{urlRow}}
    </div>`;
}}

function escHtml(s) {{
  return String(s || '—')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}}

// Create markers
const markers = [];
let activePopup = null;

LISTINGS.forEach(function(f) {{
  const color  = f.source === 'JKK' ? COLOR_JKK : COLOR_UR;
  const border = f.source === 'JKK' ? '#997700' : '#6f0080';
  const radius = Math.max(7, Math.min(16, 7 + (f.area_sqm || 0) / 20));

  const circle = L.circleMarker([f.lat, f.lon], {{
    radius:      radius,
    fillColor:   color,
    color:       border,
    weight:      2,
    opacity:     0.9,
    fillOpacity: 0.75,
  }});

  const popupContent = buildPopup(f);
  const popup = L.popup({{ maxWidth: 320, autoPan: false }}).setContent(popupContent);

  // Hover: open/close popup
  circle.on('mouseover', function(e) {{
    if (!activePopup) {{
      circle.bindPopup(popup).openPopup();
    }}
  }});
  circle.on('mouseout', function(e) {{
    if (activePopup !== circle) {{
      circle.closePopup();
    }}
  }});
  // Click: pin popup open
  circle.on('click', function(e) {{
    if (activePopup === circle) {{
      activePopup = null;
      circle.closePopup();
    }} else {{
      if (activePopup) activePopup.closePopup();
      activePopup = circle;
      circle.bindPopup(popup).openPopup();
    }}
    L.DomEvent.stopPropagation(e);
  }});

  circle._source = f.source;
  circle._name   = f.name.toLowerCase();
  circle._ward   = f.ward.toLowerCase();

  const cluster = f.source === 'JKK' ? clusterJKK : clusterUR;
  cluster.addLayer(circle);
  markers.push(circle);
}});

map.addLayer(clusterJKK);
map.addLayer(clusterUR);

// Dismiss pinned popup when clicking map background
map.on('click', function() {{
  if (activePopup) {{
    activePopup.closePopup();
    activePopup = null;
  }}
}});

// Fit map to markers
const allLatLons = LISTINGS.map(f => [f.lat, f.lon]);
if (allLatLons.length > 0) {{
  map.fitBounds(L.latLngBounds(allLatLons), {{ padding: [40, 40] }});
}} else {{
  map.setView([35.68, 139.69], 11);
}}

// --- Filtering ---
function applyFilters() {{
  const showJKK  = document.getElementById('chk-jkk').checked;
  const showUR   = document.getElementById('chk-ur').checked;
  const query    = document.getElementById('search-box').value.toLowerCase().trim();
  let shown = 0;

  clusterJKK.clearLayers();
  clusterUR.clearLayers();

  markers.forEach(function(m) {{
    const srcOK  = (m._source === 'JKK' && showJKK) || (m._source === 'UR' && showUR);
    const textOK = !query || m._name.includes(query) || m._ward.includes(query);
    if (srcOK && textOK) {{
      (m._source === 'JKK' ? clusterJKK : clusterUR).addLayer(m);
      shown++;
    }}
  }});

  document.getElementById('stat-shown').textContent = shown;
}}

document.getElementById('chk-jkk').addEventListener('change', applyFilters);
document.getElementById('chk-ur').addEventListener('change', applyFilters);
document.getElementById('search-box').addEventListener('input', applyFilters);
</script>
</body>
</html>"""

    MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    MAP_PATH.write_text(html, encoding="utf-8")

    # Mirror to docs/index.html for GitHub Pages
    DOCS_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOCS_MAP_PATH.write_text(html, encoding="utf-8")

    logger.info(
        "Map saved: %s (%d/%d listings with coordinates)",
        MAP_PATH.name, total_with_coords, total_listings,
    )
