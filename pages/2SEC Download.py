import pandas as pd
import streamlit as st
from utils.database._connector import SECDatabase
from utils.secscraper.sec_class import SECData, TickerData

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

### Choose a Company to download from SEC

""")
col1, col2 = st.columns([1, 3])
ticker_choice = col1.selectbox("Title",
                               options=tickers['title'], key="ticker_list")
upsert_submissions = col1.checkbox("Update submissions in database")
upsert_filings = col1.checkbox("Update filings in database")

if col1.button("Request from SEC"):
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
    with st.expander('Show filings'):
        st.dataframe(ticker_data._filings)
        col3, col4 = st.columns([1, 1])
        col3.download_button(
            label="Download Submissions as csv", data=csv, file_name=f"{ticker_data.ticker}_filings.csv")
        # col4.download_button(
        #     label="Download Filings as json", data=ticker_data.submissions, file_name=f"{ticker_data.ticker}_submissions.json", mime="application/json")
    # st.write(ticker_data.submissions)
