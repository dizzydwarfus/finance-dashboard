import pandas as pd
import streamlit as st
from utils.database._connector import SECDatabase
from utils.secscraper.sec_class import SECData, TickerData
from utils._utils import get_filing_facts
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

st.markdown(
    """
# SEC Scraper

### Choose a Company to download from SEC

""")

with st.expander('Important Disclaimer'):
    st.warning('This page is still under development, please use with caution.')
    st.info(
        'The SEC database is updated daily, so if you do not see the latest filings for a company, please try again later.')
    st.info(
        'The facts can be scraped from the filings, but the names of the facts are not standardized, but all facts with float values should be present. ')

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
def convert_df(df: pd.DataFrame):
    return df.to_csv(index=False).encode('utf-8')


@st.cache_data
def convert_facts_df(df: pd.DataFrame):
    start_end = df.pivot_table(
        index=['labelText', 'segment', 'startDate', 'endDate',], values='value', aggfunc='sum')
    instant = df.pivot_table(
        index=['labelText', 'segment', 'instant',], values='value', aggfunc='sum')
    with pd.ExcelWriter('./data.xlsx') as writer:
        start_end.to_xlsx(writer, index=False,
                          sheet_name='start_end').encode('utf-8')
        instant.to_xlsx(writer, index=False,
                        sheet_name='instant').encode('utf-8')


csv = convert_df(ticker_data.filings)
start_year = ticker_data.filings['filingDate'].dt.date.min()
end_year = ticker_data.filings['filingDate'].dt.date.max()
file_period = f'{start_year}_to_{end_year}'
col1.download_button(
    label="Download Filings as csv", data=csv, file_name=f"{ticker_data.ticker}_filings_{file_period}.csv")

col2.write(ticker_data.__repr_html__(), unsafe_allow_html=True)
# st.write(ticker_data.__dict__, unsafe_allow_html=True)

with st.expander('Scrape Filings'):
    filing_chosen = None
    filing_available = None
    col5, col6, col7, col8, _, _, col9 = st.columns(
        [1, 0.5, 0.5, 0.5, 1, 0.5, 1])
    form = col5.selectbox("Choose a filing to scrape", index=None,
                          options=sorted(ticker_data.forms), placeholder='Select a form...', key='scraping_form')
    mode = col6.radio("Select mode", options=[
                      "Range", "Single"], key='filing_mode')
    year_options = ticker_data.filings[ticker_data.filings['form']
                                       == form]['filingDate'].dt.year.unique()

    if mode == "Range":
        start_year = col7.selectbox(
            "Choose a Start Year", options=sorted(year_options), key='start_year',)

        end_year = col8.selectbox(
            "Choose a End Year", options=year_options, key='end_year',)
        filing_available = ticker_data.filings[(ticker_data.filings['form'] == form) & (
            ticker_data.filings['filingDate'].dt.year >= start_year) & (ticker_data.filings['filingDate'].dt.year <= end_year)]

    elif mode == "Single":
        date_options = ticker_data.filings[(
            ticker_data.filings['form'] == form)]['filingDate'].dt.date.unique()
        date = col7.selectbox(
            "Choose a date", options=date_options, key='scraping_date')
        if form and date:
            filing_available = ticker_data.filings.loc[(ticker_data.filings['form'] == form) & (
                ticker_data.filings['filingDate'].dt.date == date)]

    st.divider()
    st.write('Filings Available:')
    st.write(filing_available)
    st.divider()

    if filing_available is not None:
        filing_to_scrape = filing_available.to_dict(
            orient='records')

    if st.button('Scrape Facts'):
        labels, calc, defn, context, facts, metalinks, merged_facts, failed_folders = get_filing_facts(
            ticker=ticker_data, filings_to_scrape=filing_to_scrape)
        presented_facts = merged_facts.loc[~merged_facts['labelText'].isnull(), [
            'labelText', 'segment', 'startDate', 'endDate', 'instant', 'value', 'unitRef']]

        final_df = presented_facts.loc[(~presented_facts['value'].str.contains(
            '[^0-9\.\-]|(^\d+\-\d+\-\d+$)')) & (presented_facts['value'] != "")].copy()
        final_df['value'] = final_df['value'].astype(float)
        final_df['segment'] = final_df['segment']\
            .str.replace(f'{ticker.lower()}:', '')\
            .str.replace(f'us-gaap:', '')\
            .apply(lambda x: x[-1] if isinstance(x, list) else x)\
            .str.replace(pat=r'([A-Z])', repl=r' \1', regex=True).str.strip()
        # start_end = final_df.pivot_table(
        #     index=['labelText', 'segment', 'startDate', 'endDate',], values='value', aggfunc='sum')
        start_end = final_df.dropna(axis=0, subset=['startDate', 'endDate'])[['labelText', 'segment', 'unitRef',
                                                                              'startDate', 'endDate', 'value']].sort_values(by=['labelText', 'segment', 'startDate', 'endDate',])
        instant = final_df.dropna(axis=0, subset=['instant'])[
            ['labelText', 'segment', 'unitRef', 'instant', 'value']].sort_values(by=['labelText', 'segment', 'instant',])

        excel_final_facts = convert_df(final_df)

        st.dataframe(start_end, use_container_width=True)
        st.dataframe(instant, use_container_width=True)
        facts_period = f'{start_year}_to_{end_year}' if mode == 'Range' else date
        st.download_button(label="Download Facts as CSV", data=excel_final_facts,
                           file_name=f"{ticker_data.ticker}_{form}_{facts_period}.csv")
