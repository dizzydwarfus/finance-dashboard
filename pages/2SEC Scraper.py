# Third-party Libraries
import pandas as pd
import streamlit as st

# Internal Imports
from utils.database._connector import SECDatabase
from utils.secscraper.sec_class import SECData, TickerData
from utils.secscraper._utils import (
    reverse_standard_mapping,
    get_filing_facts,
    clean_values_in_facts,
    clean_values_in_segment,
    get_monthly_period,
    translate_labels_to_standard_names,
)
from utils.secscraper._mapping import STANDARD_NAME_MAPPING
from utils._sec_page_utils import (
    filter_dataframe,
    get_unique_sorted_options,
    plot_metric_df,
)

st.set_page_config(
    page_title="Investment Dashboard", page_icon=":moneybag:", layout="wide"
)

mongo = SECDatabase(st.secrets["mongosec"]["host"])

reversed_mapping = reverse_standard_mapping(standard_name_mapping=STANDARD_NAME_MAPPING)


@st.cache_resource(ttl=86400)  # wrapper to cache the function
def sec_init():
    return SECData()


@st.cache_resource(ttl=86400)  # wrapper to cache TickerData
def ticker_init(ticker):
    return TickerData(ticker)


sec = sec_init()
tickers = sec.cik_list.astype(str).set_index("ticker")

st.markdown(
    """
# SEC Scraper

### Choose a Company to download from SEC

"""
)

with st.expander("Important Disclaimer"):
    st.warning("This page is still under development, please use with caution.")
    st.info(
        "The SEC database is updated daily, so if you do not see the latest filings for a company, please try again later."
    )
    st.info(
        "The facts can be scraped from the filings, but the names of the facts are not standardized, but all facts with float values should be present. "
    )

col1, col2 = st.columns([1, 3])
ticker_choice = col1.selectbox(
    "Company Name", options=tickers["title"], key="ticker_list"
)
upsert_submissions = col1.checkbox("Update submissions in database")
upsert_filings = col1.checkbox("Update filings in database")

ticker = tickers.loc[tickers["title"] == ticker_choice].index[0]
ticker_data = ticker_init(ticker)
col1.success(f"Request for {ticker_choice} with {ticker_data.cik} was successful ✅")
ticker_data.submissions.pop("filings")
if upsert_submissions:
    mongo.insert_submission(submission=ticker_data._submissions)
if upsert_filings:
    mongo.insert_filings(
        cik=ticker_data.cik, filings=ticker_data.submissions["filings"]
    )


@st.cache_data
def convert_df(df: pd.DataFrame):
    return df.to_csv(index=False).encode("utf-8")


@st.cache_data
def convert_facts_df(df: pd.DataFrame):
    start_end = df.pivot_table(
        index=[
            "labelText",
            "segment",
            "startDate",
            "endDate",
        ],
        values="value",
        aggfunc="sum",
    )
    instant = df.pivot_table(
        index=[
            "labelText",
            "segment",
            "instant",
        ],
        values="value",
        aggfunc="sum",
    )
    with pd.ExcelWriter("./data.xlsx") as writer:
        start_end.to_xlsx(writer, index=False, sheet_name="start_end").encode("utf-8")
        instant.to_xlsx(writer, index=False, sheet_name="instant").encode("utf-8")


csv = convert_df(ticker_data.filings)
start_year = ticker_data.filings["filingDate"].dt.date.min()
end_year = ticker_data.filings["filingDate"].dt.date.max()
file_period = f"{start_year}_to_{end_year}"
col1.download_button(
    label="Download Filings as csv",
    data=csv,
    file_name=f"{ticker_data.ticker}_filings_{file_period}.csv",
)

col2.write(ticker_data.__repr_html__(), unsafe_allow_html=True)
# st.write(ticker_data.__dict__, unsafe_allow_html=True)

with st.container(border=True):
    st.markdown(
        """
    # Scrape Filings
    """
    )

    filing_chosen = None
    filing_available = None
    col5, col6, col7, col8, _, _ = st.columns([1, 0.5, 1, 1, 0.5, 0.5])
    form = col5.multiselect(
        "Choose a filing to scrape",
        options=sorted(ticker_data.forms),
        placeholder="Select a form...",
        key="scraping_form",
    )
    mode = col6.radio("Select mode", options=["Range", "Single"], key="filing_mode")
    year_options = ticker_data.filings[ticker_data.filings["form"].isin(form)][
        "filingDate"
    ].dt.year.unique()

    if mode == "Range":
        start_year = col7.selectbox(
            "Choose a Start Year",
            options=sorted(year_options),
            key="start_year",
        )

        end_year = col8.selectbox(
            "Choose a End Year",
            options=year_options,
            key="end_year",
        )
        filing_available = ticker_data.filings[
            (ticker_data.filings["form"].isin(form))
            & (ticker_data.filings["filingDate"].dt.year >= start_year)
            & (ticker_data.filings["filingDate"].dt.year <= end_year)
        ]

    elif mode == "Single":
        date_options = ticker_data.filings[(ticker_data.filings["form"].isin(form))][
            "filingDate"
        ].dt.date.unique()
        date = col7.selectbox(
            "Choose a date", options=date_options, key="scraping_date"
        )
        if form and date:
            filing_available = ticker_data.filings.loc[
                (ticker_data.filings["form"].isin(form))
                & (ticker_data.filings["filingDate"].dt.date == date)
            ]

    st.divider()
    st.write("Filings Available:")
    st.write(filing_available)
    st.divider()

    if filing_available is not None:
        filing_to_scrape = filing_available.to_dict(orient="records")

    if st.button("Scrape Facts"):
        st.write("Scraping Facts...")

        (
            labels,
            calc,
            defn,
            context,
            facts,
            metalinks,
            merged_facts,
            failed_folders,
        ) = get_filing_facts(ticker=ticker_data, filings_to_scrape=filing_to_scrape)

        # introduces columns 'period' and 'monthsEnded'
        final_df = get_monthly_period(merged_facts)

        # remove non-numeric values from 'factValue' column
        final_df = clean_values_in_facts(merged_facts)

        final_df = clean_values_in_segment(
            # convert segment axis and segment values to readable names
            merged_facts=final_df,
            labels_df=labels,
        )

        final_df = translate_labels_to_standard_names(
            # translate labels to standard names
            merged_facts=final_df,
            standard_name_mapping=reversed_mapping,
        )

        final_df = final_df.drop_duplicates(
            subset=[
                "standardName",
                "segmentAxis",
                "segmentValue",
                "startDate",
                "endDate",
                "instant",
                "factValue",
            ]
        ).sort_values(
            by=["standardName", "segmentAxis", "segmentValue", "startDate", "endDate"]
        )

        excel_final_facts = convert_df(final_df)

        facts_period = f"{start_year}_to_{end_year}" if mode == "Range" else date

        st.download_button(
            label="Download Facts as CSV",
            data=excel_final_facts,
            file_name=f"{ticker_data.ticker}_{form}_{facts_period}.csv",
        )

        st.session_state["final_df"] = final_df
        st.session_state["scraped_form"] = form
        st.success("Scraping Completed ✅")


with st.container(border=True):
    st.markdown(
        """
    # Analyze Facts
    """
    )

    if "final_df" not in st.session_state:
        st.warning("Please scrape facts first")
        st.stop()

    col1, col2, col3, col4, _, _ = st.columns([1, 1, 1, 1, 0.5, 0.5])

    # Initial DataFrame from session state
    df_to_plot = st.session_state["final_df"]

    # Metric selection
    metric_options = get_unique_sorted_options(df_to_plot, "standardName")
    metrics = col1.multiselect("Choose Metric(s)", options=metric_options)
    df_to_plot = filter_dataframe(df_to_plot, "standardName", metrics)

    # Segment selection based on filtered metrics
    segment_options = get_unique_sorted_options(
        df_to_plot[df_to_plot["standardName"].isin(metrics)], "segmentAxis"
    )
    segments = col2.multiselect("Choose Segment(s)", options=segment_options)
    df_to_plot = filter_dataframe(df_to_plot, "segmentAxis", segments)

    # Segment value selection based on filtered segments
    segment_suboptions = get_unique_sorted_options(
        df_to_plot[df_to_plot["segmentAxis"].isin(segments)], "segmentValue"
    )
    segment_values = col3.multiselect(
        "Choose Segment Value(s)", options=segment_suboptions
    )
    df_to_plot = filter_dataframe(df_to_plot, "segmentValue", segment_values)

    # Months ended selection based on current DataFrame state
    months_ended_options = get_unique_sorted_options(df_to_plot, "monthsEnded")
    months_ended = col4.multiselect("Choose Months Ended", options=months_ended_options)
    df_to_plot = filter_dataframe(df_to_plot, "monthsEnded", months_ended)

    st.dataframe(df_to_plot, use_container_width=True)

    # TODO: Add a section to plot the data
    # metric_df = prepare_metric_df_for_graph(df_to_plot)
    fig = plot_metric_df(df_to_plot)
    st.plotly_chart(fig, use_container_width=True)


# TODO: separate the scraping mechanism into backend API
# TODO: airflow to schedule scraping
# TODO: frontend in streamlit/other framework/perhaps js frameworks
