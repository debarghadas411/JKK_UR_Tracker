import streamlit as st
import pandas as pd
from pathlib import Path
import streamlit.components.v1 as components

# 1. Page Configuration
st.set_page_config(
    page_title="JKK + UR Housing Tracker",
    page_icon="🏙️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for Premium Dark Theme & Animations
st.markdown("""
    <style>
    /* Global Styles */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    /* Animation */
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }
    .main .block-container {
        animation: fadeIn 0.8s ease-out;
    }

    /* Metrics Styling */
    [data-testid="stMetric"] {
        background: rgba(30, 41, 59, 0.7);
        border: 1px solid rgba(59, 130, 246, 0.2);
        padding: 20px;
        border-radius: 16px;
        backdrop-filter: blur(10px);
        transition: all 0.3s ease;
    }
    [data-testid="stMetric"]:hover {
        transform: translateY(-5px);
        border-color: #3b82f6;
        box-shadow: 0 10px 20px rgba(0,0,0,0.2);
    }

    /* Sidebar Styling */
    [data-testid="stSidebar"] {
        background-color: #0f172a;
        border-right: 1px solid rgba(255,255,255,0.05);
    }

    /* Tab Styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
        background-color: transparent;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: #1e293b;
        border-radius: 10px 10px 0 0;
        gap: 1px;
        padding: 10px 20px;
        color: #94a3b8;
        transition: all 0.2s ease;
    }
    .stTabs [aria-selected="true"] {
        background-color: #3b82f6 !important;
        color: white !important;
    }

    /* Buttons */
    .stButton>button {
        border-radius: 12px;
        transition: all 0.2s;
    }
    .stButton>button:hover {
        transform: scale(1.02);
    }

    /* Header Colors */
    h1 { background: linear-gradient(90deg, #3b82f6, #60a5fa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: 800; }
    h2, h3 { color: #f8fafc; font-weight: 600; }
    
    </style>
""", unsafe_allow_html=True)

# Constants & Language Mapping
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
MAP_FILE = PROJECT_ROOT / "docs" / "index.html"

LANG_CONFIG = {
    "English 🇬🇧": {
        "file": DATA_DIR / "listings_english.tsv",
        "col_name": "Building Name",
        "col_ward": "Ward / Area",
        "col_rent": "Monthly Rent (¥)",
        "col_source": "Source",
        "col_area": "Area (sqm)",
        "col_floor_plan": "Floor Plan",
        "col_dist": "Distance to Shimbashi (km)",
        "col_time": "Train Time to Shimbashi (min)",
        "col_url": "Detail URL",
        "defaults": ["Building Name", "Monthly Rent (¥)", "Floor Plan", "Ward / Area", "Area (sqm)", "Train Time to Shimbashi (min)", "Source", "Detail URL"]
    },
    "Japanese 🇯🇵": {
        "file": DATA_DIR / "listings.tsv",
        "col_name": "住宅名 (Building Name)",
        "col_ward": "地域 (Ward)",
        "col_rent": "家賃円 (Rent ¥)",
        "col_source": "ソース (Source)",
        "col_area": "床面積㎡ (Area sqm)",
        "col_floor_plan": "間取り (Floor Plan)",
        "col_dist": "新橋駅距離km (Dist to Shimbashi km)",
        "col_time": "新橋駅電車分 (Train min to Shimbashi)",
        "col_url": "詳細URL (Detail URL)",
        "defaults": ["住宅名 (Building Name)", "家賃円 (Rent ¥)", "間取り (Floor Plan)", "地域 (Ward)", "床面積㎡ (Area sqm)", "新橋駅電車分 (Train min to Shimbashi)", "ソース (Source)", "詳細URL (Detail URL)"]
    }
}

# 2. Sidebar Configuration & Global Filters
# Deployment Sync Trigger: v1.0.1
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/city-buildings.png", width=80)
    st.title("Search Hub")
    
    selected_lang_label = st.radio(
        "Localization",
        options=list(LANG_CONFIG.keys()),
        index=0
    )
    
    cfg = LANG_CONFIG[selected_lang_label]
    
    st.divider()
    st.subheader("🛠️ Quick Filters")

# 3. Optimized Data Loading & Filtering
@st.cache_data
def load_data(file_path):
    try:
        if not file_path.exists(): return None
        return pd.read_csv(file_path, sep='\t')
    except Exception: return None

raw_df = load_data(cfg["file"])

if raw_df is not None:
    # Build Sidebar Filters Dynamically
    with st.sidebar:
        # Rent Filter
        min_rent = int(raw_df[cfg["col_rent"]].min()) if not raw_df.empty else 0
        max_rent = int(raw_df[cfg["col_rent"]].max()) if not raw_df.empty else 1000000
        if min_rent == max_rent: max_rent = min_rent + 1000
        rent_range = st.slider(
            "Rent Range (¥)", 
            min_rent, max_rent, (min_rent, max_rent),
            step=1000
        )

        # Area Filter
        min_area = float(raw_df[cfg["col_area"]].min()) if not raw_df.empty else 0.0
        max_area = float(raw_df[cfg["col_area"]].max()) if not raw_df.empty else 200.0
        if min_area == max_area: max_area = min_area + 10.0
        area_range = st.slider(
            "Area Range (sqm)",
            min_area, max_area, (min_area, max_area),
            step=1.0
        )

        # Distance to Shimbashi Filter
        if cfg["col_dist"] in raw_df.columns:
            min_dist = float(raw_df[cfg["col_dist"]].min()) if not raw_df.empty else 0.0
            max_dist = float(raw_df[cfg["col_dist"]].max()) if not raw_df.empty else 50.0
            if min_dist == max_dist: max_dist = min_dist + 5.0
            dist_range = st.slider(
                "Dist to Shimbashi (km)",
                min_dist, max_dist, (min_dist, max_dist),
                step=0.5
            )
        else:
            dist_range = (0.0, 1000.0)

        # Time to Shimbashi Filter
        if cfg["col_time"] in raw_df.columns:
            min_time = int(raw_df[cfg["col_time"]].min()) if not raw_df.empty else 0
            max_time = int(raw_df[cfg["col_time"]].max()) if not raw_df.empty else 120
            if min_time == max_time: max_time = min_time + 10
            time_range = st.slider(
                "Time to Shimbashi (min)",
                min_time, max_time, (min_time, max_time),
                step=5
            )
        else:
            time_range = (0, 1000)
        
        # Ward Filter
        wards = sorted(raw_df[cfg["col_ward"]].dropna().unique())
        selected_wards = st.multiselect("Select Wards", options=wards, default=[])

        # Floor Plan Filter
        floor_plans = sorted(raw_df[cfg["col_floor_plan"]].dropna().unique())
        selected_floor_plans = st.multiselect("Floor Plans", options=floor_plans, default=[])
        
        # Source Filter
        sources = sorted(raw_df[cfg["col_source"]].unique())
        selected_sources = st.multiselect("Data Source", options=sources, default=sources)

    # Apply Filters
    df = raw_df.copy()
    df = df[
        (df[cfg["col_rent"]] >= rent_range[0]) & 
        (df[cfg["col_rent"]] <= rent_range[1]) &
        (df[cfg["col_area"]] >= area_range[0]) &
        (df[cfg["col_area"]] <= area_range[1]) &
        (df[cfg["col_source"]].isin(selected_sources))
    ]
    
    if cfg["col_dist"] in df.columns:
        df = df[
            (df[cfg["col_dist"]] >= dist_range[0]) &
            (df[cfg["col_dist"]] <= dist_range[1])
        ]

    if cfg["col_time"] in df.columns:
        df = df[
            (df[cfg["col_time"]] >= time_range[0]) &
            (df[cfg["col_time"]] <= time_range[1])
        ]

    if selected_wards:
        df = df[df[cfg["col_ward"]].isin(selected_wards)]
    
    if selected_floor_plans:
        df = df[df[cfg["col_floor_plan"]].isin(selected_floor_plans)]

    # 4. Main UI Layout
    st.title("🏙️ JKK + UR Tokyo Navigator")

    tab_data, tab_map = st.tabs(["📊 Housing Listings", "🗺️ Vacancy Map"])

    with tab_data:
        # Metrics Row
        m_col1, m_col2, m_col3 = st.columns(3)
        with m_col1:
            st.metric("Found Rooms", len(df))
        with m_col2:
            avg_rent = int(df[cfg["col_rent"]].mean()) if len(df) > 0 else 0
            st.metric("Avg Rent", f"¥{avg_rent:,}")
        with m_col3:
            jkk_count = len(df[df[cfg["col_source"]] == "JKK"])
            st.metric("JKK / UR Split", f"{jkk_count} JKK | {len(df)-jkk_count} UR")

        # Column Selection
        with st.expander("⚙️ Customize Table Columns", expanded=False):
            all_columns = df.columns.tolist()
            selected_columns = st.multiselect(
                "Columns to display:",
                options=all_columns,
                default=[c for c in cfg["defaults"] if c in all_columns]
            )

        # Main Table
        if selected_columns:
            st.dataframe(
                df[selected_columns],
                use_container_width=True,
                hide_index=True,
                column_config={
                    cfg["col_url"]: st.column_config.LinkColumn("🔗 View Listing"),
                    cfg["col_rent"]: st.column_config.NumberColumn("Rent", format="¥%d"),
                    cfg["col_area"]: st.column_config.NumberColumn("Area", format="%.1f ㎡"),
                }
            )
        else:
            st.warning("Please select at least one column.")

    with tab_map:
        st.subheader("Interactive Hotspot Map")
        if MAP_FILE.exists():
            with open(MAP_FILE, 'r', encoding='utf-8') as f:
                html_content = f.read()
            components.html(html_content, height=750, scrolling=True)
            st.caption("✨ Full-screen experience available via GitHub Pages.")
        else:
            st.info("Map data is being synchronized... Please refresh shortly.")

else:
    st.error(f"⚠️ Critical Error: Could not find '{cfg['file']}'. Ensure the tracker has run successfully.")

# Footer
st.divider()
st.markdown("""
<div style='text-align: center; color: #64748b; font-size: 0.8rem;'>
    Designed for JKK + UR Tokyo Tracker • Auto-refresh active • <a href='https://github.com/debarghadas411/JKK_UR_Tracker' style='color: #3b82f6;'>Source</a>
</div>
""", unsafe_allow_html=True)
