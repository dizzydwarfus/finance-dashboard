import streamlit as st
import requests

# download company financial statements
@st.cache_data(ttl=86400)
def get_statement(ticker: str, statement: str, api_key: str) -> dict:
    """
    Downloads statement or profile for a given company.

    Parameters:
    ticker (str): The stock ticker symbol for the company.
    statement (str): The type of financial statement to download ['income-statement', 'balance-sheet-statement', 'cash-flow-statement', 'profile'].
    api_key (str): The API key to use for authentication.

    Returns:
    dict: A dictionary containing the financial statement data for the specified company.
    """
    r = requests.get(
        f"https://financialmodelingprep.com/api/v3/{statement}/{ticker}?apikey={api_key}")
    r = r.json()
    return r


# download stock split
def download_stocksplit(ticker: str, api_key: str) -> dict:
    r = requests.get(
        f"https://financialmodelingprep.com/api/v3/historical-price-full/stock_split/{ticker}?apikey={api_key}")
    r = r.json()
    return r


# download company real-time stock price
def realtime_price(ticker: str, api_key: str) -> dict:
    r = requests.get(
        f"https://financialmodelingprep.com/api/v3/quote-short/{ticker}?apikey={api_key}")
    r = r.json()
    return r


# download company stock peers
@st.cache_data
def stock_peers(ticker, api_key: str):
    r = requests.get(
        f"https://financialmodelingprep.com/api/v4/stock_peers?symbol={ticker}&apikey={api_key}")
    r = r.json()
    return r