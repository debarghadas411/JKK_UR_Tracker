"""
Pre-computes and caches per-region data for every ward/city in the listings:
  - Straight-line (haversine) distance from the region centre to Shimbashi station
  - Estimated train travel time to Shimbashi

Transit graph build strategy (tries each source in order, stops on first success):
  1. OpenStreetMap Overpass API — full Tokyo train/subway graph from route relations
  2. Toei Train GTFS (Mobility Database, CC-BY) — covers Toei subway lines;
     uses real stop_times for accurate travel durations
  3. Distance-based estimate — haversine / AVG_TRAIN_SPEED_KMH (fallback)

All tools are open-source / free with no registration required.

Cache files written to data/:
  region_transit_cache.json  — per-region results, keyed by ward/city name
  transit_graph_cache.json   — transit graph (built once, reused every run)

Only regions absent from the cache trigger network requests.
Delete transit_graph_cache.json to force a graph rebuild with fresh data.
"""

import csv
import heapq
import io
import json
import logging
import math
import time
import zipfile
from collections import defaultdict
from pathlib import Path

import requests

from utils.paths import DATA_DIR, CONFIG_FILE

logger = logging.getLogger(__name__)

# Shimbashi station (新橋) — JR/subway hub in central Tokyo
SHIMBASHI_LAT = 35.6659
SHIMBASHI_LON = 139.7573

# Tokyo metropolitan area bounding box (south, west, north, east)
TOKYO_BBOX = "35.4,138.8,36.2,140.2"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Public Overpass API endpoints (tried in order until one succeeds)
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
]

# Toei Train GTFS from the Mobility Database (CC-BY licence, no key needed)
TOEI_GTFS_URL = (
    "https://storage.googleapis.com/storage/v1/b/mdb-latest"
    "/o/jp-tokyo-toei-train-gtfs-3176.zip?alt=media"
)

HEADERS = {"User-Agent": "JKK-Tracker/1.0 (open-source housing tracker)"}

# Nominatim policy: at most 1 request/second
NOMINATIM_DELAY = 1.2

# Conservative effective train speed in Tokyo (km/h); accounts for dwell time
AVG_TRAIN_SPEED_KMH = 35.0

# Maximum plausible distance between two adjacent train stops
MAX_EDGE_KM = 50.0

# Shimbashi is only confidently identified if a graph node is within this range
SHIMBASHI_SNAP_KM = 0.5

# Transfer edges: stops within this radius are assumed co-located (same station)
TRANSFER_THRESHOLD_KM = 0.35
TRANSFER_TIME_MIN     = 5.0

DATA_DIR           = DATA_DIR
REGION_CACHE_FILE  = DATA_DIR / "region_transit_cache.json"
TRANSIT_GRAPH_FILE = DATA_DIR / "transit_graph_cache.json"


# ---------------------------------------------------------------------------
# Haversine distance
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Geocoding (Nominatim)
# ---------------------------------------------------------------------------

def _geocode(region_name: str) -> tuple[float, float] | None:
    """Return (lat, lon) for a Japanese ward/city name, or None on failure."""
    for query in (f"{region_name}, Tokyo, Japan", f"{region_name}, Japan"):
        time.sleep(NOMINATIM_DELAY)
        try:
            r = requests.get(
                NOMINATIM_URL,
                params={"q": query, "format": "json", "limit": 1, "countrycodes": "jp"},
                headers=HEADERS,
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
        except Exception as exc:
            logger.warning("Nominatim error for %r: %s", query, exc)
    return None


# ---------------------------------------------------------------------------
# Transit graph: shared helpers
# ---------------------------------------------------------------------------

def _add_transfer_edges(
    nodes: dict[str, list[float]],
    edges: dict[str, dict[str, float]],
) -> int:
    """
    Add transfer edges between stops within TRANSFER_THRESHOLD_KM.
    This connects separate nodes for different lines at the same physical station.
    Uses latitude-sorted scan for O(n log n + n * local_density) performance.
    Returns the number of new edges added.
    """
    node_list = sorted(nodes.items(), key=lambda x: x[1][0])
    lat_band = TRANSFER_THRESHOLD_KM / 111.0

    added = 0
    for i, (ai, ac) in enumerate(node_list):
        lon_band = TRANSFER_THRESHOLD_KM / (111.0 * math.cos(math.radians(ac[0])))
        for bi, bc in node_list[i + 1:]:
            if bc[0] - ac[0] > lat_band:
                break
            if abs(ac[1] - bc[1]) > lon_band:
                continue
            d = haversine_km(ac[0], ac[1], bc[0], bc[1])
            if d > TRANSFER_THRESHOLD_KM:
                continue
            if TRANSFER_TIME_MIN < edges.get(ai, {}).get(bi, float("inf")):
                edges.setdefault(ai, {})[bi] = TRANSFER_TIME_MIN
                added += 1
            if TRANSFER_TIME_MIN < edges.get(bi, {}).get(ai, float("inf")):
                edges.setdefault(bi, {})[ai] = TRANSFER_TIME_MIN
    return added


# ---------------------------------------------------------------------------
# Transit graph source 1: OpenStreetMap Overpass API
# ---------------------------------------------------------------------------

def _build_graph_from_overpass() -> dict | None:
    """
    Try each Overpass endpoint in turn. Return a graph dict on success, None on failure.
    Uses stop-role node members from route relations; edge weight = dist / AVG_TRAIN_SPEED_KMH.
    """
    query = f"""
[out:json][timeout:180];
rel["type"="route"]["route"~"train|subway|monorail|light_rail"]({TOKYO_BBOX})->.routes;
(
  node(r.routes:"stop");
  node(r.routes:"stop_entry_only");
  node(r.routes:"stop_exit_only");
  node(r.routes:"platform");
)->.stops;
(
  .routes;
  .stops;
);
out body;
"""
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            logger.info("Trying Overpass endpoint: %s", endpoint)
            r = requests.post(
                endpoint, data={"data": query}, headers=HEADERS, timeout=300
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            logger.warning("Overpass endpoint %s failed: %s", endpoint, exc)
            continue

        elements = data.get("elements", [])
        node_map: dict[int, list[float]] = {
            e["id"]: [e["lat"], e["lon"]]
            for e in elements
            if e["type"] == "node" and "lat" in e and "lon" in e
        }
        if not node_map:
            logger.warning("Overpass returned no nodes from %s — skipping.", endpoint)
            continue

        stop_roles = {"stop", "stop_entry_only", "stop_exit_only", "platform"}
        edges: dict[str, dict[str, float]] = {}

        for elem in elements:
            if elem["type"] != "relation":
                continue
            raw_stops = [
                m["ref"]
                for m in elem.get("members", [])
                if m["type"] == "node" and m.get("role", "") in stop_roles
            ]
            stops: list[int] = []
            for sid in raw_stops:
                if not stops or sid != stops[-1]:
                    stops.append(sid)
            for i in range(len(stops) - 1):
                a, b = stops[i], stops[i + 1]
                if a not in node_map or b not in node_map:
                    continue
                dist = haversine_km(*node_map[a], *node_map[b])
                if dist > MAX_EDGE_KM or dist < 1e-6:
                    continue
                t_min = (dist / AVG_TRAIN_SPEED_KMH) * 60.0
                sa, sb = str(a), str(b)
                edges.setdefault(sa, {})[sb] = min(edges.get(sa, {}).get(sb, float("inf")), t_min)
                edges.setdefault(sb, {})[sa] = min(edges.get(sb, {}).get(sa, float("inf")), t_min)

        nodes = {str(k): v for k, v in node_map.items()}
        added = _add_transfer_edges(nodes, edges)
        logger.info(
            "Overpass graph: %d nodes, %d edge-sets, %d transfer edges added",
            len(nodes), len(edges), added,
        )
        return {"nodes": nodes, "edges": edges, "source": "overpass"}

    return None


# ---------------------------------------------------------------------------
# Transit graph source 2: Toei Train GTFS (Mobility Database, CC-BY)
# ---------------------------------------------------------------------------

def _parse_hms(t: str) -> int:
    """Parse HH:MM:SS (GTFS may use hours > 23) to total seconds."""
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def _build_graph_from_gtfs() -> dict | None:
    """
    Download Toei Train GTFS and build a transit graph using actual stop_times.

    Edge weights are average trip travel times between consecutive stops, derived
    directly from GTFS departure/arrival timestamps — NOT distance estimates.

    Coverage: Toei Asakusa (A), Mita (I), Shinjuku (S), Oedo (E) lines +
    Nippori-Toneri Liner and Arakawa tram.
    Shimbashi (新橋, stop A-10) is on the Asakusa line.
    """
    logger.info("Downloading Toei Train GTFS from Mobility Database...")
    try:
        r = requests.get(TOEI_GTFS_URL, headers=HEADERS, timeout=60)
        r.raise_for_status()
    except Exception as exc:
        logger.warning("Failed to download Toei GTFS: %s", exc)
        return None

    try:
        zf = zipfile.ZipFile(io.BytesIO(r.content))
    except Exception as exc:
        logger.warning("Failed to open Toei GTFS zip: %s", exc)
        return None

    # Parse stops
    nodes: dict[str, list[float]] = {}
    with zf.open("stops.txt") as fh:
        for row in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig")):
            try:
                nodes[row["stop_id"]] = [float(row["stop_lat"]), float(row["stop_lon"])]
            except (KeyError, ValueError):
                continue

    # Parse stop_times: group by trip_id, ordered by stop_sequence
    trips: dict[str, list[tuple[int, str, int]]] = defaultdict(list)
    with zf.open("stop_times.txt") as fh:
        for row in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig")):
            try:
                trips[row["trip_id"]].append(
                    (int(row["stop_sequence"]), row["stop_id"], _parse_hms(row["departure_time"]))
                )
            except (KeyError, ValueError):
                continue

    # Build edges: average actual travel time between consecutive stops across all trips
    edge_samples: dict[tuple[str, str], list[float]] = defaultdict(list)
    for seqs in trips.values():
        seqs.sort()
        for i in range(len(seqs) - 1):
            a_seq, a_id, a_dep = seqs[i]
            b_seq, b_id, b_dep = seqs[i + 1]
            if b_dep > a_dep:
                t_min = (b_dep - a_dep) / 60.0
                if 0 < t_min < 60:  # sanity: max 60 min between consecutive stops
                    edge_samples[(a_id, b_id)].append(t_min)

    edges: dict[str, dict[str, float]] = {}
    for (a, b), samples in edge_samples.items():
        avg_t = sum(samples) / len(samples)
        edges.setdefault(a, {})[b] = min(edges.get(a, {}).get(b, float("inf")), avg_t)
        edges.setdefault(b, {})[a] = min(edges.get(b, {}).get(a, float("inf")), avg_t)

    added = _add_transfer_edges(nodes, edges)
    logger.info(
        "GTFS graph (Toei): %d stops, %d edge-sets, %d transfer edges added",
        len(nodes), len(edges), added,
    )
    return {"nodes": nodes, "edges": edges, "source": "gtfs_toei"}


# ---------------------------------------------------------------------------
# Transit graph: loader (tries Overpass → GTFS, caches result)
# ---------------------------------------------------------------------------

def _build_transit_graph() -> dict:
    """
    Build a transit graph using the best available source:
      1. Overpass API (full Tokyo network)
      2. Toei GTFS (partial: Toei lines only, but uses real GTFS stop_times)
    Returns an empty graph if both sources fail.
    """
    logger.info("Building transit graph (runs once, then cached)...")

    graph = _build_graph_from_overpass()
    if graph and graph["nodes"]:
        return graph

    logger.info("Overpass unavailable — falling back to Toei GTFS.")
    graph = _build_graph_from_gtfs()
    if graph and graph["nodes"]:
        return graph

    logger.warning("All transit data sources failed. Transit times will be unavailable.")
    return {"nodes": {}, "edges": {}, "source": "none"}


def _get_graph_refresh_days() -> int | None:
    """
    Read transit.graph_refresh_days from config.yaml.
    Returns the integer value, or 90 as default, or None if explicitly null.
    """
    try:
        import yaml
        with CONFIG_FILE.open(encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        val = cfg.get("transit", {}).get("graph_refresh_days", 90)
        return int(val) if val is not None else None
    except Exception:
        return 90


def _load_graph() -> dict:
    """Return the cached transit graph, building and caching it if absent or stale."""
    if TRANSIT_GRAPH_FILE.exists():
        refresh_days = _get_graph_refresh_days()
        if refresh_days is None:
            # Never auto-refresh — use cached graph forever
            logger.debug("Loading cached transit graph (auto-refresh disabled).")
            with TRANSIT_GRAPH_FILE.open(encoding="utf-8") as fh:
                return json.load(fh)
        age_days = (time.time() - TRANSIT_GRAPH_FILE.stat().st_mtime) / 86400
        if age_days < refresh_days:
            logger.debug(
                "Loading cached transit graph (age %.1f days / limit %d days)",
                age_days, refresh_days,
            )
            with TRANSIT_GRAPH_FILE.open(encoding="utf-8") as fh:
                return json.load(fh)
        else:
            logger.info(
                "Transit graph is %.1f days old (limit %d) — rebuilding with fresh OSM/GTFS data.",
                age_days, refresh_days,
            )
            # Delete region cache so transit times are recomputed with the new graph
            if REGION_CACHE_FILE.exists():
                REGION_CACHE_FILE.unlink()
                logger.info("Deleted region transit cache — will recompute with fresh graph.")
            TRANSIT_GRAPH_FILE.unlink()

    graph = _build_transit_graph()
    if graph["nodes"]:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with TRANSIT_GRAPH_FILE.open("w", encoding="utf-8") as fh:
            json.dump(graph, fh)
        logger.info(
            "Transit graph cached at %s (%d nodes, source=%s)",
            TRANSIT_GRAPH_FILE, len(graph["nodes"]), graph.get("source"),
        )
    return graph


# ---------------------------------------------------------------------------
# Routing utilities
# ---------------------------------------------------------------------------

def _nearest_node(
    graph: dict,
    lat: float,
    lon: float,
    max_dist_km: float = float("inf"),
) -> str | None:
    """Return the ID of the nearest graph node within max_dist_km, or None."""
    best_id, best_dist = None, float("inf")
    for nid, coords in graph["nodes"].items():
        d = haversine_km(lat, lon, coords[0], coords[1])
        if d < best_dist:
            best_id, best_dist = nid, d
    if best_dist > max_dist_km:
        return None
    return best_id


def _find_shimbashi_node(graph: dict) -> str | None:
    """
    Return the nearest graph node to Shimbashi station.
    Returns None if no node is within SHIMBASHI_SNAP_KM (graph doesn't cover
    the Shimbashi area).
    """
    return _nearest_node(graph, SHIMBASHI_LAT, SHIMBASHI_LON, max_dist_km=SHIMBASHI_SNAP_KM)


def _dijkstra(graph: dict, start: str, end: str) -> float | None:
    """Return shortest travel time in minutes from start to end, or None if unreachable."""
    edges = graph["edges"]
    dist: dict[str, float] = {start: 0.0}
    heap: list[tuple[float, str]] = [(0.0, start)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist.get(u, float("inf")):
            continue
        if u == end:
            return d
        for v, w in edges.get(u, {}).items():
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                heapq.heappush(heap, (nd, v))
    return None


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------

def load_region_cache() -> dict:
    """Load and return the region transit cache dict."""
    if REGION_CACHE_FILE.exists():
        with REGION_CACHE_FILE.open(encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def save_region_cache(cache: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with REGION_CACHE_FILE.open("w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=2)


def refresh_region_cache(region_names: list[str]) -> dict:
    """
    Force-recompute transit data for all given regions, ignoring the existing cache.
    Deletes region_transit_cache.json and rebuilds it using the current transit graph
    (the graph itself is NOT force-rebuilt — it follows graph_refresh_days as usual).
    Returns the updated cache dict.
    """
    if REGION_CACHE_FILE.exists():
        REGION_CACHE_FILE.unlink()
        logger.info(
            "Region transit cache cleared — recomputing for %d region(s).", len(region_names)
        )
    return ensure_regions_cached(region_names)


def ensure_regions_cached(region_names: list[str]) -> dict:
    """
    Ensure every region in region_names has an entry in the cache.
    Only regions not yet cached trigger geocoding and transit-graph routing.
    The transit graph is loaded (or built) at most once per call.

    Transit time strategy (in priority order):
      1. Graph-based routing (Overpass or GTFS) if the nearest graph stop is
         within MAX_WALK_KM of the region centroid.
      2. Distance-based estimate: haversine / effective_speed + access overhead.
         Used when graph routing is unavailable or the graph doesn't cover the area.

    Returns the full cache dict (including pre-existing entries).
    """
    # Minimum walking distance to reach a transit stop; beyond this, graph
    # routing is treated as inapplicable for partial-coverage graphs (e.g. Toei).
    MAX_WALK_KM_FOR_PARTIAL_GRAPH = 1.0

    cache = load_region_cache()
    missing = [r for r in region_names if r not in cache]
    if not missing:
        return cache

    logger.info(
        "Computing transit data for %d new region(s): %s",
        len(missing),
        ", ".join(missing),
    )

    graph: dict | None = None
    shimbashi_node: str | None = None
    graph_source: str = "none"

    for region in missing:
        coords = _geocode(region)
        if not coords:
            logger.warning("Could not geocode %r — storing null values.", region)
            cache[region] = {"distance_km": None, "transit_minutes": None}
            continue

        lat, lon = coords
        dist_km = round(haversine_km(lat, lon, SHIMBASHI_LAT, SHIMBASHI_LON), 1)

        transit_min: int | None = None
        try:
            if graph is None:
                graph = _load_graph()
                graph_source = graph.get("source", "none")
                shimbashi_node = _find_shimbashi_node(graph)
                if shimbashi_node is None:
                    logger.warning(
                        "Shimbashi not found in transit graph (source=%s). "
                        "Will use distance-based estimates.",
                        graph_source,
                    )

            if shimbashi_node and graph["nodes"]:
                start_node = _nearest_node(graph, lat, lon)
                if start_node:
                    nearest_dist = haversine_km(lat, lon, *graph["nodes"][start_node])
                    # For partial-coverage graphs (GTFS Toei), only route if the
                    # nearest stop is within practical walking distance.
                    is_full_graph = graph_source == "overpass"
                    walk_ok = is_full_graph or nearest_dist <= MAX_WALK_KM_FOR_PARTIAL_GRAPH
                    if walk_ok:
                        raw = _dijkstra(graph, start_node, shimbashi_node)
                        if raw is not None:
                            transit_min = round(raw)
        except Exception as exc:
            logger.warning("Transit routing failed for %r: %s", region, exc)

        # Fall back to a distance-based estimate when graph routing is unavailable
        if transit_min is None:
            # Effective speed increases with distance (local→rapid→express)
            effective_speed = AVG_TRAIN_SPEED_KMH if dist_km < 20 else 45.0
            transit_min = round((dist_km / effective_speed) * 60 + 15)
            logger.debug(
                "  %s: using distance estimate (%.1f km / %.0f km/h + 15 min access)",
                region, dist_km, effective_speed,
            )

        cache[region] = {"distance_km": dist_km, "transit_minutes": transit_min}
        logger.info(
            "  %s → Shimbashi: %.1f km, %d min by train (graph=%s)",
            region, dist_km, transit_min, graph_source,
        )

    save_region_cache(cache)
    return cache
