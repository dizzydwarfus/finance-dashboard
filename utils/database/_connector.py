import streamlit as st
from pymongo import MongoClient


@st.cache_resource
def init_connection():
    return MongoClient(**st.secrets["mongo"])


@st.cache_resource(ttl=86400)  # only refresh after 24h
def get_data():
    client = init_connection()
    db = client.FinanceApp
    balance_sheet_collection = db.balance_sheet
    income_collection = db.income_statement
    cash_collection = db.cash_flow_statement
    company_profile = db.company_profile
    historical = db.historical
    stock_split = db.stock_split
    return balance_sheet_collection, income_collection, cash_collection, company_profile, historical, stock_split
