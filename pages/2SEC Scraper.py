import pandas as pd
import streamlit as st
from utils.database._connector import SECDatabase
from utils.secscraper.sec_class import SECData, TickerData
from utils.secscraper._utils import get_filing_facts, clean_values_in_facts, clean_values_in_segment, split_facts_into_start_instant, get_monthly_period
import plotly.express as px
import plotly.graph_objects as go

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
    st.info('The SEC database is updated daily, so if you do not see the latest filings for a company, please try again later.')
    st.info('The facts can be scraped from the filings, but the names of the facts are not standardized, but all facts with float values should be present. ')

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
    col5, col6, col7, col8, _, _ = st.columns([1, 0.5, 1, 1, 0.5, 0.5])
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
        filing_to_scrape = filing_available.to_dict(orient='records')

    if st.button('Scrape Facts'):
        st.write('Scraping Facts...')

        labels, calc, defn, context, facts, metalinks, merged_facts, failed_folders = get_filing_facts(
            ticker=ticker_data, filings_to_scrape=filing_to_scrape)

        final_df = get_monthly_period(merged_facts)

        final_df = clean_values_in_facts(merged_facts)

        final_df = clean_values_in_segment(merged_facts=final_df)

        final_df, start_end, instant = split_facts_into_start_instant(final_df)

        excel_final_facts = convert_df(final_df)

        facts_period = f'{start_year}_to_{end_year}' if mode == 'Range' else date

        st.download_button(label="Download Facts as CSV", data=excel_final_facts,
                           file_name=f"{ticker_data.ticker}_{form}_{facts_period}.csv")

        st.session_state['final_df'] = final_df
        st.success('Scraping Completed ✅')


with st.expander('Show Facts'):
    if 'final_df' not in st.session_state:
        st.warning('Please scrape facts first')
        st.stop()

    df_to_plot = st.session_state['final_df']

    metric_options = df_to_plot['labelText'].sort_values().unique()
    metrics = st.multiselect('Choose metric(s)', options=metric_options)

    segment_options = df_to_plot.loc[df_to_plot['labelText'].isin(
        metrics), 'segment'].sort_values().unique()

    segments = st.multiselect('Choose segment(s)', options=segment_options)
    st.divider()

    metric_df = df_to_plot[df_to_plot['labelText'].isin(
        metrics) & df_to_plot['segment'].isin(segments)]

    # Pivot the DataFrame
    pivot_df = metric_df.pivot(
        index=['endDate', 'Months Ended'], columns='segment', values='value')

    # Calculate the difference
    diff_df = pivot_df.diff()

    # Melt the DataFrame back to the original format
    melt_df = diff_df.reset_index().melt(id_vars=['endDate', 'Months Ended'],
                                         var_name='segment', value_name='change')

    # Merge the difference back to the original DataFrame
    metric_df = metric_df.merge(melt_df, on=['endDate', 'segment'])

    # st.dataframe(pivot_df, use_container_width=True)
    # st.dataframe(diff_df, use_container_width=True)
    # st.dataframe(melt_df, use_container_width=True)

    # Create a new column 'color' that indicates whether the value has increased or decreased
    metric_df['color'] = 'neutral'
    metric_df.loc[metric_df['change'] > 0, 'color'] = 'increase'
    metric_df.loc[metric_df['change'] < 0, 'color'] = 'decrease'
    st.dataframe(metric_df, use_container_width=True)

    # Create a line plot
    fig = px.line(metric_df, x='endDate', y='value',
                  color='segment', line_group='segment',
                  hover_data={'change': ':,'},)
    # Overlay a scatter plot for the individual points
    fig.add_trace(
        go.Scatter(
            x=metric_df['endDate'],
            y=metric_df['value'],
            mode='markers',
            marker=dict(
                color=metric_df['color'].map(
                    {'increase': 'green', 'decrease': 'red', 'neutral': 'grey'}),
                size=15,
                symbol=metric_df['color'].map(
                    {'increase': 'triangle-up', 'decrease': 'triangle-down', 'neutral': 'circle'})
            ),
            hoverinfo='skip',
            showlegend=False
        )
    )
    for trace in fig.data:
        print(trace)
    # Customize the layout
    fig.update_layout(
        title='Metrics over time',
        xaxis_title='End Date',
        yaxis_title='Value',
        legend_title='Segment',
        font=dict(
            family='Courier New, monospace',
            size=18,
            color='RebeccaPurple'
        ),
        hovermode='x unified'
    )
    fig.update_xaxes(autorange=True)
    fig.update_yaxes(autorange=True, rangemode="tozero")
    # Show the plot
    st.plotly_chart(fig, use_container_width=True)
