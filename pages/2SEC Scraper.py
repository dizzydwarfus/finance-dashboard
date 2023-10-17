import pandas as pd
import streamlit as st
from utils.database._connector import SECDatabase
from utils.secscraper.sec_class import SECData, TickerData
import json

st.set_page_config(page_title="Investment Dashboard",
                   page_icon=":moneybag:",
                   layout="wide")

mongo = SECDatabase(st.secrets['mongosec']['host'])


@st.cache_resource(ttl=86400)  # wrapper to cache the function
def sec_init():
    return SECData()


@st.cache_resource(ttl=86400)  # wrapper to cache TickerData
def ticker_init(ticker):
    return TickerData(ticker)


sec = sec_init()
tickers = sec.cik_list.astype(str).set_index('ticker')

# TODO: Sentiment analysis on tickers - https://www.alphavantage.co/documentation/ for
# TODO: compare DCF calculated stock price, with current price (repeat for past years, to see trend)
# TODO: show % difference for past DCF calculated values and calculate safety of margin, pick best metric from that.
# TODO: show extra tab with historical stock price using yfinance
# TODO: show technical indicators, and perform backtest
# TODO: use ML model to predict stock price
# TODO: Use LangChain+Open AI API to build researcher agent to research based on user prompt

st.markdown(
    """
# SEC Scraper

### Choose a Company to download from SEC

""")

st.warning('This page is still under development, please use with caution. 🚧 Only filings that are in XML format (not HTML) can be parsed properly. HTML parsing is coming soon!')

col1, col2 = st.columns([1, 3])
ticker_choice = col1.selectbox("Company Name",
                               options=tickers['title'], key="ticker_list")
upsert_submissions = col1.checkbox("Update submissions in database")
upsert_filings = col1.checkbox("Update filings in database")

ticker = tickers.loc[tickers['title'] == ticker_choice].index[0]
ticker_data = ticker_init(ticker)
col1.success(
    f"Request for {ticker_choice} with {ticker_data.cik} was successful ✅")
ticker_data.submissions.pop('filings')
if upsert_submissions:
    mongo.insert_submission(submission=ticker_data._submissions)
if upsert_filings:
    mongo.insert_filings(cik=ticker_data.cik,
                         filings=ticker_data.submissions['filings'])


@st.cache_data
def convert_df(df):
    return df.to_csv(index=False).encode('utf-8')


csv = convert_df(ticker_data._filings)
col2.write(ticker_data.__repr_html__(), unsafe_allow_html=True)
# st.write(ticker_data.__dict__, unsafe_allow_html=True)
with st.expander('Show Filings Information'):
    st.dataframe(ticker_data.filings)
    st.download_button(
        label="Download Filings as csv", data=csv, file_name=f"{ticker_data.ticker}_filings.csv")

with st.expander('Scrape Filings'):
    filing_chosen = None
    filing_available = None
    col5, col6, col7 = st.columns([1, 1, 1])
    form = col5.selectbox("Choose a filing to scrape", index=None,
                          options=sorted(ticker_data.forms), placeholder='Select a form...', key='scraping_form')
    year_options = ticker_data.filings[ticker_data.filings['form']
                                       == form]['filingDate'].dt.year.unique()
    year = col6.selectbox(
        "Choose a year", options=year_options, key='scraping_year',)
    if year:
        date_options = ticker_data.filings[(ticker_data.filings['form'] == form) & (
            ticker_data.filings['filingDate'].dt.year == year)]['filingDate'].dt.date.unique()
        date = col7.selectbox(
            "Choose a date", options=date_options, key='scraping_date')
    if form and year and date:
        filing_available = ticker_data.filings.loc[(ticker_data.filings['form'] == form) & (
            ticker_data.filings['filingDate'].dt.year == year) & (ticker_data.filings['filingDate'].dt.date == date)]

    st.divider()
    st.write('Filings Available:')
    st.write(filing_available)
    st.divider()
    if filing_available is not None:
        filing_chosen = st.selectbox(
            "Choose a filing to scrape", options=filing_available['accessionNumber'], key='scraping_filing')
    if st.button('Scrape Facts') and filing_chosen:
        filing_to_scrape = filing_available.loc[filing_available['accessionNumber'] == filing_chosen].to_dict(
            orient='records')[0]
        facts, context, metalinks, final_facts = ticker_data.get_facts_for_each_filing(
            filing_to_scrape)
        st.write('Facts')
        st.write(facts)
        st.write('Context')
        st.write(context)
        st.write('Metalinks')
        st.write(metalinks)
        st.write('Final Facts Table')
        st.write(pd.DataFrame(final_facts))
