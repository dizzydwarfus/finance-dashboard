# Built-in imports
import datetime as dt

# Third-party imports
import streamlit as st
from pymongo.collection import Collection
from pymongo import DESCENDING

#Internal imports
from utils._alphavantageAPI import stock_price_api
from utils._fmpAPI import download_stocksplit, get_statement

@st.cache_data
def get_tickers(_collection: Collection) -> list:
    tickers = list(set([i['symbol'] for i in _collection.find()]))
    return tickers


@st.cache_data
def read_profile(ticker: str, _mongodb_collection: Collection) -> dict:

    statement = [i for i in _mongodb_collection.find(
        {'symbol': ticker}).sort('date', DESCENDING)]

    return statement


# @st.cache_data
def read_statement(ticker, _mongodb_collection: Collection) -> list:

    statement = [i for i in _mongodb_collection.find(
        {'symbol': ticker}).sort('date', DESCENDING)]

    return statement


# access entries in collection
def access_entry(_collection_name, entry_name, entry_value, return_value):
    data = _collection_name.find({entry_name: entry_value})

    data = [i[return_value] for i in data]

    return data


# Function to insert file to database
def insert_to_mongoDB(collection, ticker, statement, second_key, fmp_api, alpha_vantage_api):
    if statement == 'profile':
        file = get_statement(ticker, statement, fmp_api)
        file[0]['index_id'] = f"{file[0]['symbol']}_{file[0][second_key]}"
        file[0]['lastUpdate'] = dt.datetime.strptime(
            file[0]['lastUpdate'], '%Y-%m-%d %H:%M:%S')
        if st.session_state['profile_update']:
            collection.delete_one({'symbol': ticker})
        try:
            collection.insert_one(file[0])
            # collection.insert_one(file2[0])
            return st.success(f"{ticker} {statement} updated!", icon="✅")
        except:
            return st.error(f"{ticker} {statement} already exists", icon="🚨")

    elif statement == 'stock_price':
        file = stock_price_api(ticker)
        for i, x in file['Time Series (Daily)'].items():
            x['index_id'] = f"{ticker}_{i}"
            x['symbol'] = f"{ticker}"
            x[second_key] = dt.datetime.strptime(i, '%Y-%m-%d')
            x['open'] = x['1. open']
            x['high'] = x['2. high']
            x['low'] = x['3. low']
            x['close'] = x['4. close']
            x['volume'] = x['5. volume']
            x.pop('1. open')
            x.pop('2. high')
            x.pop('3. low')
            x.pop('4. close')
            x.pop('5. volume')

        ids = [x['index_id'] for i, x in file['Time Series (Daily)'].items(
        ) if x['index_id'] not in access_entry(collection, 'symbol', ticker, 'index_id')]
        try:
            collection.insert_many(
                [x for i, x in file['Time Series (Daily)'].items() if x['index_id'] in ids])
            return st.success(f"{ticker} {statement} updated!", icon="✅")

        except:
            return st.error(f"{ticker} {statement} already exists", icon="🚨")

    elif statement == 'stock_split':
        file = download_stocksplit(ticker)
        for i in file['historical']:
            i['index_id'] = f"{file['symbol']}_{i[second_key]}"
            i['symbol'] = f"{file['symbol']}"
            i[second_key] = dt.datetime.strptime(i['date'], '%Y-%m-%d')

        ids = [i['index_id'] for i in file['historical'] if i['index_id']
               not in access_entry(collection, 'symbol', ticker, 'index_id')]

        try:
            collection.insert_many(
                [i for i in file['historical'] if i['index_id'] in ids])
            return st.success(f"{ticker} {statement} updated!", icon="✅")

        except:
            return st.error(f"{ticker} {statement} already exists", icon="🚨")
    else:
        file = get_statement(ticker, statement, fmp_api)

        if len(file) <= 1:
            pass
        else:
            for i in file:
                i['index_id'] = f"{i['symbol']}_{i[second_key]}"

            ids = [i['index_id'] for i in file if i['index_id']
                   not in access_entry(collection, 'symbol', ticker, 'index_id')]

            try:
                collection.insert_many(
                    [i for i in file if i['index_id'] in ids])
                return st.success(f"{ticker} {statement} updated!", icon="✅")
            except:
                return st.error(f"{ticker} {statement} already exists", icon="🚨")
