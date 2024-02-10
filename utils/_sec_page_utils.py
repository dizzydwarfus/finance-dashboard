# Third-party Libraries
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import pandas as pd

def filter_dataframe(df, column_name, selected_values):
    """
    Filter the DataFrame based on selected values of a specific column.
    If selected values are provided, filters the DataFrame; otherwise, returns the original DataFrame.
    """
    if selected_values:
        return df[df[column_name].isin(selected_values)]
    return df

def get_unique_sorted_options(df, column_name):
    """
    Returns a sorted list of unique options for a specific column in the DataFrame.
    """
    return df[column_name].sort_values().unique()


def prepare_metric_df_for_graph(metric_df: pd.DataFrame) -> pd.DataFrame:
        try:
            # Pivot the DataFrame
            pivot_df = metric_df.pivot(
                index=['endDate', 'monthsEnded'], columns='segmentAxis', values='factValue')

            # Calculate the difference
            diff_df = pivot_df.diff()

            # Melt the DataFrame back to the original format
            melt_df = diff_df.reset_index().melt(id_vars=['endDate', 'monthsEnded'],
                                                var_name='segmentAxis', value_name='change')

            # Merge the difference back to the original DataFrame
            # Create a new column 'color' that indicates whether the value has increased or decreased
            metric_df['color'] = 'neutral'
            metric_df.loc[metric_df['change'] > 0, 'color'] = 'increase'
            metric_df.loc[metric_df['change'] < 0, 'color'] = 'decrease'
            metric_df = metric_df.merge(melt_df, on=['endDate', 'labelText_segmentAxis'])

        except Exception as e:
            st.error(e, icon='🚨')


def plot_metric_df(metric_df):
    # Create a line plot
    if metric_df['instant'] is not None:
         date_col = 'instant'
    else:
         date_col = 'endDate'

    fig = px.line(metric_df, x=date_col, y='factValue',
                  color='segmentValue', line_group='segmentValue',
                  #   hover_data={'change': ':,'},
                  )
    # Overlay a scatter plot for the individual points
    # fig.add_trace(
    #     go.Scatter(
    #         x=metric_df[date_col],
    #         y=metric_df['factValue'],
    #         mode='markers',
    #         marker=dict(
    #             # color=metric_df['color'].map(
    #             #     {'increase': 'green', 'decrease': 'red', 'neutral': 'grey'}),
    #             size=10,
    #             # symbol=metric_df['color'].map(
    #             #     {'increase': 'triangle-up', 'decrease': 'triangle-down', 'neutral': 'circle'})
    #         ),
    #         hoverinfo='skip',
    #         showlegend=False
    #     )
    # )
    for trace in fig.data:
        print(trace)
    # Customize the layout
    fig.update_layout(
        title='Metrics over time',
        xaxis_title='Date',
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

    return fig