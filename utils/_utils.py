# Built-in libraries
import datetime as dt
import math
import os

# Third-party libraries
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Internal imports
from utils._alphavantageAPI import treasury
from utils._mongo import read_statement


@st.cache_resource
def get_api():
    # fmp_api = st.secrets["fmp_api"]
    # alpha_vantage_api = st.secrets["rapidapi_key"]
    fmp_api = os.getenv("FMP_API_KEY")
    alpha_vantage_api = os.getenv("ALPHAVANTAGE_API_KEY")
    return fmp_api, alpha_vantage_api


def generate_statements_type(**mongo_collections) -> dict:
    statements_dict = {
        "Income Statement": mongo_collections["_income_collection"],
        "Cash Flow Statement": mongo_collections["_cash_collection"],
        "Balance Sheet": mongo_collections["_balance_sheet_collection"],
    }
    return statements_dict


@st.cache_data
def generate_terms():
    terms_interested = {
        "Revenue": "revenue",
        "Gross margin%": "grossProfitRatio",
        "Operating Income": "operatingIncome",
        "Operating Margin %": "operatingIncomeRatio",
        "Net Income": "netIncome",
        "Net Income Margin": "netIncomeRatio",
        "Earnings per Share": "epsdiluted",
        "Shares Oustanding (diluted)": "weightedAverageShsOutDil",
        "Dividends": "dividendsPaid",
        "Operating Cash Flow": "operatingCashFlow",
        "Cap Spending": "capitalExpenditure",
        "Free Cash Flow": "freeCashFlow",
        "Free Cash Flow per Share": "freeCashFlowpershare",
        "Working Capital": "totalCurrentAssets - totalCurrentLiabilities",
        "Net Debt": "netDebt",
    }
    return terms_interested


# generate key metrics table
def generate_key_metrics(
    financial_statement: dict, _list_of_metrics: list
) -> pd.DataFrame:
    temp_list = []
    dict_holder = {}
    columns = financial_statement[0].keys()

    # loop over the list of interested columns (metrics)
    for n in _list_of_metrics:
        if (
            n in columns
        ):  # check if columns in interested list can be found in columns of financial statement
            # loop over the range of years
            for i, x in enumerate(financial_statement[::-1]):
                dict_holder[x["calendarYear"]] = x[f"{n}"]

            temp_list.append(dict_holder)
            dict_holder = {}

        else:
            pass

    df = pd.DataFrame.from_records(
        temp_list, index=[items for items in _list_of_metrics if items in columns]
    )

    return df


# define index for each json
def define_id(json_file):
    for i in json_file:
        i["index_id"] = f"{i['symbol']}_{i['date']}"

    return json_file


# function to generate growth over time plots
@st.cache_data
def generate_plots(dataframe, arrangement: tuple, metric, terms_interested: dict):
    # create columns to place charts based on arrangement specified (columns in each row)
    cols = st.columns(arrangement)
    dataframe = dataframe.T
    metric2 = [terms_interested[i] for i in metric]
    m = 0

    for i, n in enumerate(metric2):
        if n in dataframe.columns:
            # Define growth rates Y-o-Y
            growth = dataframe[f"{n}"].pct_change(periods=1).fillna(0)
            fig = make_subplots(specs=[[{"secondary_y": True}]])

            # Add traces (graphs)
            fig.add_trace(
                go.Bar(
                    x=dataframe.index,
                    y=dataframe[f"{n}"],
                    texttemplate="$%{value:,}",
                    textposition="inside",
                    name=f"{n.capitalize()}",
                ),
                secondary_y=False,
            )

            fig.add_trace(
                go.Scatter(
                    x=dataframe.index,
                    y=growth,
                    text=[i for i in growth],
                    mode="lines+markers",
                    opacity=0.3,
                    marker=dict({"color": "darkorange"}),
                    name="Growth Y-o-Y",
                ),
                secondary_y=True,
            )

            # Update figure title, legend, axes
            fig.update_layout(
                showlegend=False,
                #   template='plotly_dark',
                paper_bgcolor="#1c2541",
                plot_bgcolor="#0b132b",
                xaxis_title="Year",
                #   yaxis_title=f'{n}',
                title={
                    "text": f"<b>{metric[i].capitalize()}</b> (last {len(dataframe)} years)",
                    "x": 0.5,
                    "xanchor": "center",
                    "font": {"size": 25},
                },
                font={"size": 15},
            )
            fig.update_yaxes(showgrid=False, zeroline=True, secondary_y=False)
            fig.update_yaxes(
                title_text="Growth Y-o-Y",
                secondary_y=True,
                showgrid=False,
                zeroline=False,
            )

            # Plot the chart in its respective column based on loop
            cols[m].plotly_chart(
                fig,
                use_container_width=True,
            )


# generate plots for historical price
@st.cache_data
def historical_plots(dataframe, arrangement, date):
    cols = st.columns(arrangement)
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Add traces (graphs)
    fig.add_trace(
        go.Candlestick(
            x=dataframe.loc[
                (dataframe.index.date >= date[0]) & (dataframe.index.date < date[-1])
            ].index,
            open=dataframe["open"],
            high=dataframe["high"],
            low=dataframe["low"],
            close=dataframe["close"],
        ),
        secondary_y=False,
    )

    fig.add_trace(
        go.Bar(
            x=dataframe.loc[
                (dataframe.index.date >= date[0]) & (dataframe.index.date < date[-1])
            ].index,
            y=dataframe["volume"],
            opacity=0.2,
            marker=dict({"color": "darkorange"}),
            textposition="inside",
            name="Daily Volume",
        ),
        secondary_y=True,
    )

    # Update figure title, legend, axes
    fig.update_layout(
        height=1000,
        showlegend=False,
        #   template='plotly_dark',
        # paper_bgcolor='#1c2541',
        # plot_bgcolor="#0b132b",
        # xaxis_title='Date',
        #   yaxis_title=f'{n}',
        title={
            "text": f'<b>{dataframe["symbol"][0]} price</b> (from {date[0]}-{date[-1]})',
            "x": 0.5,
            "xanchor": "center",
            "font": {"size": 25},
        },
        font={"size": 15},
    )
    fig.update_yaxes(showgrid=False, zeroline=True, secondary_y=False)
    fig.update_yaxes(
        title_text="Daily Volume", secondary_y=True, showgrid=False, zeroline=False
    )

    cols[0].plotly_chart(
        fig,
        use_container_width=True,
    )


# function to format pandas dataframe
def make_pretty(styler, use_on=None):
    # styler.set_caption("Weather Conditions")
    # styler.format(rain_condition)
    # styler.format_index(lambda v: v.strftime("%A"))
    # styler.background_gradient(axis=None, vmin=1, vmax=5, cmap="YlGnBu")
    if use_on is None:
        styler.format(
            precision=0,
            na_rep="MISSING",
            thousands=" ",
            subset=pd.IndexSlice[
                [
                    "revenue",
                    "operatingIncome",
                    "netIncome",
                    "weightedAverageShsOutDil",
                    "operatingCashFlow",
                    "netDebt",
                    "capitalExpenditure",
                    "freeCashFlow",
                    "dividendsPaid",
                ],
                :,
            ],
        )
        styler.format(precision=0, na_rep="MISSING", thousands=" ")
        styler.format(
            precision=2,
            na_rep="MISSING",
            thousands=" ",
            subset=pd.IndexSlice[
                [
                    "grossProfitRatio",
                    "netIncomeRatio",
                    "operatingIncomeRatio",
                    "epsdiluted",
                ],
                :,
            ],
        )
        styler.map(
            lambda x: "color:red;" if (x < 0 if isinstance(x, str) else None) else None
        )
    # styler.highlight_min(color='indianred', axis=0)
    # styler.highlight_max(color='green', axis=0)
    elif use_on == "statements":
        styler.format(
            precision=0,
            na_rep="MISSING",
            thousands=" ",
            formatter={
                "grossProfitRatio": "{:.0%}",
                "ebitdaratio": "{:.0%}",
                "netIncomeRatio": "{:.0%}",
                "operatingIncomeRatio": "{:.0%}",
                "incomeBeforeTaxRatio": "{:.0%}",
                "eps": "{:.2f}",
                "epsdiluted": "{:.2f}",
            },
        )
    else:
        styler.format(na_rep="-", formatter="{:.0%}")
        styler.map(
            lambda x: "color:red;" if (x < 0 if isinstance(x, str) else None) else None
        )

    return styler


# DCF Functions


# project financials based on average growth of past_n_years into the future_n_years
def project_metric(
    df,
    metric,
    past_n_years,
    first_n_years,
    second_n_years,
    first_growth=None,
    second_growth=None,
):
    projected = [df[metric].iloc[-1]]
    if first_growth == 0:
        avg_growth = df[metric].pct_change()[-past_n_years:].mean()
        for i in range(first_n_years + second_n_years):
            projected.append(projected[i] * (1 + avg_growth))
    else:
        for i in range(first_n_years):
            projected.append(projected[i] * (1 + first_growth))
        for i in range(first_n_years, second_n_years + first_n_years):
            projected.append(projected[i] * (1 + second_growth))
    return projected


# calculate yield to maturity of company bonds


def ytm(coupon_rate, face_value, present_value, maturity_date: str):
    maturity_date = dt.datetime.strptime(maturity_date, "%Y-%m-%d")
    n_compounding_periods = math.trunc((maturity_date - dt.datetime.today()).days / 365)
    num = coupon_rate + ((face_value - present_value) / n_compounding_periods)
    den = (face_value + present_value) / 2
    YTM = num / den
    return YTM


# wacc is the minimum rate of return that the company must earn on its investments to satisfy its investors and creditors.


def wacc(
    df, risk_free_rate, beta, market_return, tax_rate, equity, debt, historical_years
):
    # beta of company stock
    # risk free rate using 2Y,5Y,10Y treasury yield
    # market return = annualized % return expected if investing in this stock
    cost_of_equity = risk_free_rate + beta * (
        market_return - risk_free_rate
    )  # estimatino based on CAPM
    # estimated based on weighted average of total interest expense and longterm debt
    cost_of_debt = (1 - tax_rate) * (
        df["interestExpense"][-historical_years:]
        / df["longTermDebt"][-historical_years:]
    ).mean()
    # debt = sum of principal amounts of all outstanding debt securities issued by the company, including bonds, loans, and other debt instruments
    # equity = market cap = shares * price per share
    total_market_value = equity + debt
    weight_of_equity = equity / total_market_value
    weight_of_debt = debt / total_market_value
    wacc = weight_of_equity * cost_of_equity + weight_of_debt * cost_of_debt
    return wacc


# Define a function to calculate the intrinsic value


def intrinsic_value(
    df,
    ebitda_margin,
    terminal_growth_rate,
    wacc,
    tax_rate,
    depreciation,
    capex,
    nwc,
    years,
    metric,
    projected_metric,
):
    # Calculate the free cash flows for each year
    if metric == "revenue":
        ebitda = [revenue * ebitda_margin for revenue in projected_metric]
        ebit = [ebitda[i] - depreciation for i in range(len(ebitda))]
        tax_paid = [-1 * tax_rate * ebit[i] for i in range(len(ebit))]
        net_income = [ebit[i] + tax_paid[i] for i in range(len(ebit))]
        free_cash_flow = [net_income[i] - capex - nwc for i in range(len(net_income))]

        # Calculate the terminal value
        last_free_cash_flow = free_cash_flow[-1]
        terminal_value = (
            last_free_cash_flow
            * (1 + terminal_growth_rate)
            / (wacc - terminal_growth_rate)
        )

        # Calculate the present value of the cash flows
        discount_factors = [1 / (1 + wacc) ** i for i in range(1, years + 1)]
        pv_cash_flows = [free_cash_flow[i] * discount_factors[i] for i in range(years)]
        pv_terminal_value = [terminal_value * discount_factors[-1]]
        intrinsic_value = sum(pv_cash_flows) + sum(pv_terminal_value)

        return intrinsic_value / df["weightedAverageShsOutDil"].iloc[-1]
    else:
        # Calculate the terminal value
        last_year = projected_metric[-1]
        terminal_value = (
            last_year * (1 + terminal_growth_rate) / (wacc - terminal_growth_rate)
        )
        # Calculate the present value of metric
        discount_factors = [1 / (1 + wacc) ** i for i in range(1, years + 1)]
        pv = [projected_metric[i] * discount_factors[i] for i in range(years)]
        pv_terminal_value = [terminal_value * discount_factors[-1]]
        intrinsic_value = abs(sum(pv) + sum(pv_terminal_value))

        if metric == "epsdiluted":
            return intrinsic_value

        else:
            return intrinsic_value / df["weightedAverageShsOutDil"].iloc[-1]


# function to create financial_statements page
def create_financial_page(
    ticker,
    company_profile_info,
    col3,
    p: list,
    statements_type: list,
    terms_interested: dict,
    api_key: str,
    historical,
):
    p[0].markdown(
        f"""<span style='font-size:1.5em;'>CEO</span>
    :green[{company_profile_info['ceo']}]

    """,
        unsafe_allow_html=True,
    )

    p[1].markdown(
        f"""<span style='font-size:1.5em;'>Exchange</span>
    :green[{company_profile_info['exchangeShortName']}]

    """,
        unsafe_allow_html=True,
    )

    p[2].markdown(
        f"""<span style='font-size:1.5em;'>Industry</span>
    :green[{company_profile_info['industry']}]

    """,
        unsafe_allow_html=True,
    )

    p[0].markdown(
        f"""<span style='font-size:1.5em;'>Country</span>
    :green[{company_profile_info['country']}]

    """,
        unsafe_allow_html=True,
    )

    p[1].markdown(
        f"""<span style='font-size:1.5em;'>Number of Employees</span>
    :green[{int(company_profile_info['fullTimeEmployees']):,}]

    """,
        unsafe_allow_html=True,
    )

    p[2].markdown(
        f"""<span style='font-size:1.5em;'>Sector</span>
    :green[{company_profile_info['sector']}]

    """,
        unsafe_allow_html=True,
    )

    # historical, income_tab, cash_tab, balance_tab, key_metrics_tab, charts_tab = col3.tabs(
    #     ["Historical", "Income Statement", "Cash Flow", "Balance Sheet", "Key Metrics", "Charts"], )

    (
        historical_tab,
        income_tab,
        cash_tab,
        balance_tab,
        key_metrics_tab,
        charts_tab,
        DCF_tab,
    ) = col3.tabs(
        [
            "Historical",
            "Income Statement",
            "Cash Flow",
            "Balance Sheet",
            "Key Metrics",
            "Charts",
            "DCF Calculator",
        ],
    )

    for i, x in enumerate([income_tab, cash_tab, balance_tab]):
        with x:
            col3.write(f"### {list(statements_type.keys())[i]}")
            tab_statement = read_statement(ticker, list(statements_type.values())[i])
            max_year = int(tab_statement[0]["calendarYear"]) - int(
                tab_statement[-1]["calendarYear"]
            )
            year_range = col3.slider(
                "Select year range (past n years):",
                min_value=1,
                max_value=max_year,
                value=int(max_year / 2),
                key=f"{ticker}_{x}_{i}",
            )

            year_list = list(range(year_range))

            # col3.checkbox("Use container width",
            #             value=False,
            #             key=f'use_container_width_{x}_{i}')

            df_financial_statements = pd.DataFrame.from_records(
                tab_statement[year_list[0] : year_list[-1] + 1],
                index=[tab_statement[i]["calendarYear"] for i in year_list],
            ).iloc[::1, 9:-2]
            df_financial_statements = df_financial_statements.style.pipe(
                make_pretty, use_on="statements"
            )

            col3.dataframe(
                df_financial_statements,
                use_container_width=bool(
                    "st.session_state.use_container_width_income_tab"
                ),
            )

    with key_metrics_tab:
        master_table_unformatted = pd.concat(
            [
                generate_key_metrics(
                    read_statement(ticker, statements_type[x]),
                    terms_interested.values(),
                )
                for x in statements_type
            ],
            axis=0,
        ).drop_duplicates()
        master_table_unformatted = master_table_unformatted.loc[
            ~master_table_unformatted.index.duplicated(keep="first"), :
        ]
        mt_growth = master_table_unformatted.T.pct_change(periods=1).T.style.pipe(
            make_pretty, use_on="metric"
        )
        master_table_formatted = master_table_unformatted.style.pipe(make_pretty)

        # st.metric(label=f'{mt_growth.columns[0]}', value=mt_growth.iloc[:,0].mean(skipna=True)/len(mt_growth.index), delta=mt_growth.iloc[-1,0])

        # To create the master key metrics table compiled from statements
        col3.dataframe(master_table_formatted)
        col3.write("##### Y-o-Y Growth Table")
        col3.dataframe(mt_growth)

    with charts_tab:
        chart_select = st.multiselect(
            "*Select charts to show:*",
            terms_interested.keys(),
            key=f"{ticker}_multiselect",
        )
        generate_plots(
            master_table_unformatted,
            [1],
            chart_select,
            terms_interested=terms_interested,
        )

    with historical_tab:
        df_historical = pd.DataFrame.from_records(
            [x for i, x in enumerate(historical.find({"symbol": ticker}))], index="date"
        ).sort_index()
        date_select = st.slider(
            "Select date range:",
            min_value=df_historical.index.date[0],
            max_value=df_historical.index.date[-1],
            value=(df_historical.index.date[-365], df_historical.index.date[-1]),
        )
        historical_plots(df_historical, [1], date_select)

        # TODO: insert input for entry, exit, amount, and calculate return with tax rate
    with DCF_tab:
        con1, con2, con3, con2_3 = (
            st.container(),
            st.container(),
            st.container(),
            st.container(),
        )

        c1, c2, c3 = con1.columns([0.5, 0.5, 1])

        con2.markdown(
            """

        >>##### *Set time frame (in years)*:

        """
        )

        c4, c5, c6 = con2.columns([0.5, 0.5, 0.5])

        con3.markdown(
            """

        >>##### *Main Inputs for WACC*

        """
        )
        c12, c13, c14 = con3.columns([0.5, 0.5, 0.5])

        trate_dict = {
            "3month": float(treasury("3month", api_key)["data"][0]["value"]) / 100,
            "2year": float(treasury("2year", api_key)["data"][0]["value"]) / 100,
            "5year": float(treasury("5year", api_key)["data"][0]["value"]) / 100,
            "7year": float(treasury("7year", api_key)["data"][0]["value"]) / 100,
            "10year": float(treasury("10year", api_key)["data"][0]["value"]) / 100,
        }

        avg_gr_choices = ["revenue", "epsdiluted", "dividendsPaid", "netIncome"]
        df = pd.concat(
            [
                pd.DataFrame.from_records(
                    read_statement(ticker, statements_type[x]),
                    index="calendarYear",
                    exclude=[
                        "_id",
                        "date",
                        "symbol",
                        "reportedCurrency",
                        "cik",
                        "fillingDate",
                        "acceptedDate",
                        "period",
                        "link",
                        "finalLink",
                        "index_id",
                    ],
                )
                for x in statements_type
            ],
            axis=1,
        ).T
        df = df.loc[~df.index.duplicated(keep="first"), :].T.sort_index()
        forecast_n_years = c4.number_input(
            "Forecast First n Years: ", min_value=1, step=1, value=5
        )
        forecast_m_years = c4.number_input(
            "Forecast Next m Years: ", min_value=1, step=1, value=5
        )
        historical_years = c6.number_input("Past Years: ", min_value=1, step=1, value=5)

        con2_3.markdown(
            f"""

        >>##### *Averages over last {historical_years} years*:

        """
        )

        g1, g2, g3, g4, g5 = con2_3.columns([1, 1, 1, 1, 1])

        try:
            # Define the financials of the company
            first_growth = c5.number_input(
                "Growth rate (first n years):", min_value=0.0, step=0.01, value=0.0
            )
            second_growth = c5.number_input(
                "Growth rate (next m years):", min_value=0.0, step=0.01, value=0.0
            )
            projected_revenue = project_metric(
                df,
                avg_gr_choices[0],
                past_n_years=historical_years,
                first_n_years=forecast_n_years,
                second_n_years=forecast_m_years,
                # Revenue forecast for the next five years based on growth of past n=10 years
                first_growth=first_growth,
                second_growth=second_growth,
            )
            projected_eps = project_metric(
                df,
                avg_gr_choices[1],
                past_n_years=historical_years,
                first_n_years=forecast_n_years,
                second_n_years=forecast_m_years,
                # Revenue forecast for the next five years based on growth of past n=10 years
                first_growth=first_growth,
                second_growth=second_growth,
            )
            projected_netincome = project_metric(
                df,
                avg_gr_choices[3],
                past_n_years=historical_years,
                first_n_years=forecast_n_years,
                second_n_years=forecast_m_years,
                # Revenue forecast for the next five years based on growth of past n=10 years
                first_growth=first_growth,
                second_growth=second_growth,
            )
            projected_dividends = project_metric(
                df,
                avg_gr_choices[2],
                past_n_years=historical_years,
                first_n_years=forecast_n_years,
                second_n_years=forecast_m_years,
                # Revenue forecast for the next five years based on growth of past n=10 years
                first_growth=first_growth,
                second_growth=second_growth,
            )
            # Depreciation as average of past n=historical_years years for the company
            depreciation = df["depreciationAndAmortization"][-historical_years:].mean()
            # Capital expenditures as average of past n=historical_years years for the company
            capital_expenditures = df["capitalExpenditure"][-historical_years:].mean()
            # Tax rate as average of past n=historical_years years for the company calculated by dividing tax expense by incomebeforetax
            tax_rate = (
                df["incomeTaxExpense"][-historical_years:]
                / df["incomeBeforeTax"][-historical_years:]
            ).mean()
            # Net working capital (current assets - current liabilities where current generally defines period of 12 months - assets that can be liquidated/debts that must be repayed within that time period)
            net_working_capital = (
                df["totalCurrentAssets"][-historical_years:]
                - df["totalCurrentLiabilities"][-historical_years:]
            ).mean()

            # # Define the assumptions for standard scenario
            # EBITDA margin as average of past n=historical_years years for the company
            ebitda_margin = df["ebitdaratio"][-historical_years:].mean()
            # this can be based on revenue, net income, dividendsPaid, epsdiluted, give a choice
            avg_gr_revenue = (
                df[avg_gr_choices[0]].pct_change()[-historical_years:].mean()
            )
            # this can be based on revenue, net income, dividendsPaid, epsdiluted, give a choice
            avg_gr_eps = df[avg_gr_choices[1]].pct_change()[-historical_years:].mean()
            # this can be based on revenue, net income, dividendsPaid, epsdiluted, give a choice
            avg_gr_dividends = (
                df[avg_gr_choices[2]].pct_change()[-historical_years:].mean()
            )
            # this can be based on revenue, net income, dividendsPaid, epsdiluted, give a choice
            avg_gr_netincome = (
                df[avg_gr_choices[3]].pct_change()[-historical_years:].mean()
            )

            g1.markdown(f'###### Revenue: `{"{:.1%}".format(avg_gr_revenue)}`')
            g2.markdown(f'###### EPS: `{"{:.1%}".format(avg_gr_eps)}`')
            g3.markdown(f'###### Dividends: `{"{:.1%}".format(avg_gr_dividends)}`')
            g4.markdown(f'###### Net Income: `{"{:.1%}".format(avg_gr_netincome)}`')
            g5.markdown(f'###### Tax-rate: `{"{:.1%}".format(tax_rate)}`')

            # This limits the terminal growth rate to 5% maximum
            terminal_gr_revenue = min(0.05, avg_gr_revenue)
            # This limits the terminal growth rate to 5% maximum
            terminal_gr_eps = min(0.05, avg_gr_eps)
            # This limits the terminal growth rate to 5% maximum
            terminal_gr_netincome = min(0.05, avg_gr_netincome)
            # This limits the terminal growth rate to 5% maximum
            terminal_gr_dividends = min(0.05, avg_gr_dividends)

            # # Define the WACC assumptions
            # get latest 5Y treasury yield # treasury yield (2Y, 5Y, 10Y), get realtime by querying fedAPI
            treasury_rate = c12.selectbox(
                "Risk-free Rate: ",
                ["3month", "2year", "5year", "7year", "10year", "30year"],
            )
            c12.markdown(
                f"""*3-mth*: `{"{:.2%}".format(trate_dict["3month"])}` *2-yr*: `{"{:.2%}".format(trate_dict["2year"])}` *5-yr*: `{"{:.2%}".format(trate_dict["5year"])}` *7-yr*: `{"{:.2%}".format(trate_dict["7year"])}` *10-yr*: `{"{:.2%}".format(trate_dict["10year"])}`"""
            )
            risk_free_rate = trate_dict[treasury_rate]

            # assume a 8% return is desired
            market_return = c14.number_input(
                "Expected Market Return:", min_value=0.0, step=0.005, value=0.08
            )
            beta = company_profile_info["beta"]  # beta of stock
            equity = company_profile_info["mktCap"]  # market cap of stock
            # total debt of company (excluding liabilities that are not debt)
            debt = df["totalDebt"][-historical_years:].mean()
            discount_rate = c13.number_input(
                "Discount Rate: ",
                min_value=0.01,
                step=0.01,
                value=wacc(
                    df,
                    risk_free_rate,
                    beta,
                    market_return,
                    tax_rate,
                    equity,
                    debt,
                    historical_years,
                ),
            )
            years = (
                forecast_n_years + forecast_m_years
            )  # total years to forecast forward
            DCF_revenue = round(
                intrinsic_value(
                    df,
                    ebitda_margin,
                    terminal_gr_revenue,
                    discount_rate,
                    tax_rate,
                    depreciation,
                    capital_expenditures,
                    net_working_capital,
                    years,
                    metric=avg_gr_choices[0],
                    projected_metric=projected_revenue,
                ),
                2,
            )
            DCF_eps = round(
                intrinsic_value(
                    df,
                    ebitda_margin,
                    terminal_gr_eps,
                    discount_rate,
                    tax_rate,
                    depreciation,
                    capital_expenditures,
                    net_working_capital,
                    years,
                    metric=avg_gr_choices[1],
                    projected_metric=projected_eps,
                ),
                2,
            )
            DCF_netincome = round(
                intrinsic_value(
                    df,
                    ebitda_margin,
                    terminal_gr_netincome,
                    discount_rate,
                    tax_rate,
                    depreciation,
                    capital_expenditures,
                    net_working_capital,
                    years,
                    metric=avg_gr_choices[3],
                    projected_metric=projected_netincome,
                ),
                2,
            )
            DCF_dividends = round(
                intrinsic_value(
                    df,
                    ebitda_margin,
                    terminal_gr_dividends,
                    discount_rate,
                    tax_rate,
                    depreciation,
                    capital_expenditures,
                    net_working_capital,
                    years,
                    metric=avg_gr_choices[2],
                    projected_metric=projected_dividends,
                ),
                2,
            )
            # Display the results

            con4 = st.container()
            con4.markdown("""--------""")
            c18, c19, c20, c21 = con4.columns([1, 1, 1, 1])
            c18.markdown(
                f""">#### From Revenue: `{company_profile_info['currency']} {DCF_revenue}`"""
            )
            c19.markdown(
                f""">#### From EPS: `{company_profile_info['currency']} {DCF_eps}`"""
            )
            c20.markdown(
                f""">#### From Net Income: `{company_profile_info['currency']} {DCF_netincome}`"""
            )
            c21.markdown(
                f""">#### DCF From Dividends: `{company_profile_info['currency']} {DCF_dividends}`"""
            )

        except Exception as e:
            e
            pass
