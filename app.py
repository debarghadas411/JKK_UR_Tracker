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
        "col_url": "Detail URL",
        "defaults": ["Building Name", "Monthly Rent (¥)", "Floor Plan", "Ward / Area", "Area (sqm)", "Source", "Detail URL"]
    },
    "Japanese 🇯🇵": {
        "file": DATA_DIR / "listings.tsv",
        "col_name": "住宅名 (Building Name)",
        "col_ward": "地域 (Ward)",
        "col_rent": "家賃円 (Rent ¥)",
        "col_source": "ソース (Source)",
        "col_area": "床面積㎡ (Area sqm)",
        "col_floor_plan": "間取り (Floor Plan)",
        "col_url": "詳細URL (Detail URL)",
        "defaults": ["住宅名 (Building Name)", "家賃円 (Rent ¥)", "間取り (Floor Plan)", "地域 (Ward)", "床面積㎡ (Area sqm)", "ソース (Source)", "詳細URL (Detail URL)"]
    }
}

# 2. Sidebar Configuration & Global Filters
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
        min_rent = int(raw_df[cfg["col_rent"]].min())
        max_rent = int(raw_df[cfg["col_rent"]].max())
        rent_range = st.slider(
            "Rent Range (¥)", 
            min_rent, max_rent, (min_rent, max_rent),
            step=5000
        )
        
        # Ward Filter
        wards = sorted(raw_df[cfg["col_ward"]].unique())
        selected_wards = st.multiselect("Select Wards", options=wards, default=[])
        
        # Source Filter
        sources = sorted(raw_df[cfg["col_source"]].unique())
        selected_sources = st.multiselect("Data Source", options=sources, default=sources)

    # Apply Filters
    df = raw_df.copy()
    df = df[
        (df[cfg["col_rent"]] >= rent_range[0]) & 
        (df[cfg["col_rent"]] <= rent_range[1]) &
        (df[cfg["col_source"]].isin(selected_sources))
    ]
    if selected_wards:
        df = df[df[cfg["col_ward"]].isin(selected_wards)]

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
