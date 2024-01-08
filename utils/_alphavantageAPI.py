import requests
import streamlit as st

# download stock price
def stock_price_api(ticker: str, api_key: str) -> dict:
    url = "https://alpha-vantage.p.rapidapi.com/query"
    headers = {"X-RapidAPI-Key": api_key,
               "X-RapidAPI-Host": "alpha-vantage.p.rapidapi.com"}
    querystring = {"function": "TIME_SERIES_DAILY",
                   "symbol": f"{ticker}", "outputsize": "full", "datatype": "json"}
    response = requests.request(
        "GET", url=url, headers=headers, params=querystring)
    return response.json()


# retrieve latest treasury yield
@st.cache_data(ttl=86400)
def treasury(maturiy: str, api_key: str) -> dict:
    r = requests.get(
        f"https://www.alphavantage.co/query?function=TREASURY_YIELD&interval=daily&maturity={maturiy}&apikey={api_key}")
    r = r.json()
    return r