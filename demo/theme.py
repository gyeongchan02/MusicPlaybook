"""Seoul National University inspired theme for the Streamlit demo."""

from __future__ import annotations

import streamlit as st

# 서울대 상징 남색 계열
SNU_NAVY = "#0C4DA2"
SNU_NAVY_DARK = "#083A7A"
SNU_NAVY_DEEP = "#062952"
SNU_SKY = "#E8F1FA"
SNU_GOLD = "#B8975A"
SNU_WHITE = "#FFFFFF"


def inject_snu_theme() -> None:
    st.markdown(
        f"""
        <style>
        :root {{
            --snu-navy: {SNU_NAVY};
            --snu-navy-dark: {SNU_NAVY_DARK};
            --snu-sky: {SNU_SKY};
        }}

        .stApp {{
            background: linear-gradient(180deg, #f7fafd 0%, #eef4fb 100%);
        }}

        [data-testid="stSidebar"] {{
            background: linear-gradient(180deg, {SNU_NAVY_DARK} 0%, {SNU_NAVY_DEEP} 100%);
        }}
        [data-testid="stSidebar"] * {{
            color: #f0f6ff !important;
        }}
        [data-testid="stSidebar"] .stCaption,
        [data-testid="stSidebar"] small {{
            color: #c8daf0 !important;
        }}
        [data-testid="stSidebar"] hr {{
            border-color: rgba(255,255,255,0.15);
        }}

        h1, h2, h3, h4 {{
            color: {SNU_NAVY_DARK} !important;
        }}

        .stTabs [data-baseweb="tab-list"] {{
            gap: 0.4rem;
            border-bottom: 2px solid {SNU_NAVY};
        }}
        .stTabs [data-baseweb="tab"] {{
            color: {SNU_NAVY_DARK};
            font-weight: 600;
        }}
        .stTabs [aria-selected="true"] {{
            color: {SNU_NAVY} !important;
            border-bottom: 3px solid {SNU_GOLD};
        }}

        div[data-testid="stMetric"] {{
            background: {SNU_SKY};
            border: 1px solid #b8cfe8;
            border-left: 4px solid {SNU_NAVY};
            border-radius: 0.5rem;
            padding: 0.5rem 0.75rem;
        }}
        div[data-testid="stMetric"] label {{
            color: {SNU_NAVY_DARK} !important;
        }}

        .stButton > button[kind="primary"] {{
            background: {SNU_NAVY} !important;
            border: 1px solid {SNU_NAVY_DARK} !important;
            color: white !important;
        }}
        .stButton > button[kind="primary"]:hover {{
            background: {SNU_NAVY_DARK} !important;
            border-color: {SNU_GOLD} !important;
        }}

        .stDownloadButton > button {{
            border-color: {SNU_NAVY} !important;
            color: {SNU_NAVY_DARK} !important;
        }}

        div[data-testid="stExpander"] details {{
            border: 1px solid #c5d9ef !important;
            background: #fbfdff;
        }}

        .snu-header {{
            background: linear-gradient(90deg, {SNU_NAVY_DARK}, {SNU_NAVY});
            color: white;
            padding: 1rem 1.25rem;
            border-radius: 0.6rem;
            margin-bottom: 1rem;
            border-left: 5px solid {SNU_GOLD};
        }}
        .snu-header h1, .snu-header p {{
            color: white !important;
            margin: 0;
        }}
        .snu-badge {{
            display: inline-block;
            background: {SNU_GOLD};
            color: {SNU_NAVY_DEEP};
            font-size: 0.75rem;
            font-weight: 700;
            padding: 0.15rem 0.5rem;
            border-radius: 0.25rem;
            margin-left: 0.5rem;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def snu_header(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="snu-header">
            <h1>{title} <span class="snu-badge">SNU Demo</span></h1>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
