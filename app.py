import streamlit as st
import pandas as pd
from pathlib import Path
import streamlit.components.v1 as components

# 1. Page Configuration
st.set_page_config(
    page_title="JKK + UR Housing Tracker",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for a more polished look
st.markdown("""
    <style>
    .main {
        background-color: #f8f9fa;
    }
    .stMetric {
        background-color: #ffffff;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .stDataFrame {
        border-radius: 10px;
    }
    h1 {
        color: #1e3a8a;
        font-weight: 800;
    }
    .sidebar .sidebar-content {
        background-color: #ffffff;
    }
    </style>
""", unsafe_allow_html=True)

# Constants
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
MAP_FILE = PROJECT_ROOT / "docs" / "index.html"
FILE_MAP = {
    "English 🇬🇧": DATA_DIR / "listings_english.tsv",
    "Japanese 🇯🇵": DATA_DIR / "listings.tsv"
}

# 2. Sidebar Configuration
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/home.png", width=80)
    st.title("Tracker Control")
    
    st.subheader("🌐 Localization")
    selected_lang_label = st.radio(
        "Select Language",
        options=list(FILE_MAP.keys()),
        index=0,
        help="Choose the language for the data table."
    )
    
    st.divider()
    st.caption("Auto-updating from VM every 10 mins")

# 3. Optimized Data Loading
@st.cache_data
def load_data(file_path):
    try:
        if not file_path.exists():
            return None
        df = pd.read_csv(file_path, sep='\t')
        return df
    except Exception:
        return None

# Load the selected dataset
df = load_data(FILE_MAP[selected_lang_label])

# 4. Main UI Layout
st.title("🏙️ JKK + UR Tokyo Housing")

# Create Tabs
tab_data, tab_map = st.tabs(["📊 Data Explorer", "🗺️ Interactive Map"])

with tab_data:
    if df is not None:
        # Metrics Row
        m_col1, m_col2, m_col3 = st.columns(3)
        with m_col1:
            st.metric("Available Rooms", len(df), delta=None)
        with m_col2:
            sources = df['source'].value_counts() if 'source' in df.columns else {}
            jkk_count = sources.get('JKK', 0)
            st.metric("JKK Listings", jkk_count)
        with m_col3:
            ur_count = sources.get('UR', 0)
            st.metric("UR Listings", ur_count)

        # Filters Expander
        with st.expander("🔍 Advanced Column Filters", expanded=False):
            all_columns = df.columns.tolist()
            # Default columns to show (cleaner view)
            default_cols = [c for c in ["name", "rent", "floor_plan", "ward", "area", "floor", "source", "detail_url"] if c in all_columns]
            if not default_cols: default_cols = all_columns
            
            selected_columns = st.multiselect(
                "Select columns to display:",
                options=all_columns,
                default=default_cols
            )

        # Main Table
        if selected_columns:
            st.dataframe(
                df[selected_columns],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "detail_url": st.column_config.LinkColumn("Listing Link"),
                    "rent": st.column_config.NumberColumn("Rent (¥)", format="%d"),
                }
            )
        else:
            st.warning("Please select at least one column.")
    else:
        st.error("Data files not found. Please wait for the tracker to complete a cycle.")

with tab_map:
    st.subheader("Live Vacancy Map")
    if MAP_FILE.exists():
        with open(MAP_FILE, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        components.html(html_content, height=700, scrolling=True)
        st.caption("Full screen map available at: [GitHub Pages](https://debarghadas411.github.io/JKK_UR_Tracker/)")
    else:
        st.info("Generating map... Please refresh in a moment.")

# Footer
st.divider()
st.markdown("""
<div style='text-align: center'>
    <p>Data refreshed automatically | <a href='https://github.com/debarghadas411/JKK_UR_Tracker'>Project Repository</a></p>
</div>
""", unsafe_allow_html=True)
