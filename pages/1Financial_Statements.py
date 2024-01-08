import streamlit as st
from utils._utils import create_financial_page, generate_statements_type, generate_terms, get_api
from utils.database._connector import get_data
from utils._mongo import read_profile, get_tickers
#####################################################

# Define dropdowns and set page config

#####################################################
fmp_api, alpha_vantage_api = get_api()

balance_sheet_collection, income_collection, cash_collection, company_profile, historical, stock_split = get_data()

statements_type = generate_statements_type(
    _income_collection=income_collection, _cash_collection=cash_collection, _balance_sheet_collection=balance_sheet_collection)

terms_interested = generate_terms()
tickers = get_tickers(balance_sheet_collection)

ticker_list_box = st.sidebar.selectbox(
    "Select a ticker symbol:", sorted(tickers), key="ticker_list")

companyA_info = read_profile(ticker_list_box, company_profile)[0]

company_profile.update_one({'index_id': f"{ticker_list_box}_{companyA_info['ipoDate']}"}, {
                           "$set": companyA_info}, upsert=True)

same_sector = sorted([i for i in tickers if read_profile(i, company_profile)[
                     0]['sector'] == companyA_info['sector']])

# ticker_compare = st.sidebar.selectbox(
# "Select a ticker symbol to compare:", same_sector, key="ticker_compare")

# companyB_info = read_profile(ticker_compare)[0]

# compare_companies = st.sidebar.checkbox('Compare', key='compare_companies')

#####################################################

# FInancial Statements Page

#####################################################

# if compare_companies:
#     l0, l1 = st.columns([1, 1])
#     t0, t1 = st.columns([1, 1])
#     p1, p2, p3, p4, p5, p6 = st.columns([1, 1, 1, 1, 1, 1])
#     c1, c2 = st.columns([1, 1])

#     l0.markdown(f"""

#     ![Logo]({companyA_info['image']} "Company Logo")

#     """)

#     t0.markdown(f"""


#     # {companyA_info['companyName']}
#     ###### *Ticker symbol*: {ticker_list_box}
#     ---
#     ### Company Profile

#     {companyA_info['description']}

#     *<span style="font-size:1em;">Visit [{companyA_info['website']}]({companyA_info['website']}) to learn more.</span>*

#     """, unsafe_allow_html=True)

#     l1.markdown(f"""

#     ![Logo]({companyB_info['image']} "Company Logo")

#     """)

#     t1.markdown(f"""


#     # {companyB_info['companyName']}
#     ###### *Ticker symbol*: {ticker_compare}
#     ---
#     ### Company Profile

#     {companyB_info['description']}

#     *<span style="font-size:1em;">Visit [{companyB_info['website']}]({companyB_info['website']}) to learn more.</span>*

#     """, unsafe_allow_html=True)

#     create_financial_page(ticker_list_box, companyA_info, c1, [p1, p2, p3])
#     create_financial_page(ticker_compare, companyB_info, c2, [p4, p5, p6])

# else:
st.markdown(f"""

![Logo]({companyA_info['image']} "Company Logo")

""")

st.markdown(f"""


# {companyA_info['companyName']} `{companyA_info['currency']} {companyA_info['price']}`
###### *Ticker symbol*: {ticker_list_box}
---
### Company Profile

{companyA_info['description']}

*<span style="font-size:1em;">Visit [{companyA_info['website']}]({companyA_info['website']}) to learn more.</span>*

""", unsafe_allow_html=True)

p1, p2, p3 = st.columns([1, 1, 1])

create_financial_page(ticker_list_box, companyA_info, st, [
                      p1, p2, p3], statements_type=statements_type, terms_interested=terms_interested, api_key=alpha_vantage_api, historical=historical)

st.write(same_sector)

st.markdown("***[Data provided by Financial Modeling Prep](https://financialmodelingprep.com/developer/docs/)***", unsafe_allow_html=True)

#TODO: create a new tab to compare entry and exit positions with profit including tax rate
#TODO: allow user to enter entry and exit date, amount to invest, with supposed tax rate on exit date
#TODO: create function to calculate profit based on entry and exit date and amount invested
#TODO: use plotly to visualize entry (green diamond) and exit (red diamond) positions on a candlestick/line chart