import streamlit as st
from pymongo import MongoClient, ASCENDING
from logger import MyLogger


@st.cache_resource
def init_connection():
    return MongoClient(**st.secrets["mongo"])


@st.cache_resource(ttl=86400)  # only refresh after 24h
def get_data():
    client = init_connection()
    db = client.FinanceApp
    balance_sheet_collection = db.balance_sheet
    income_collection = db.income_statement
    cash_collection = db.cash_flow_statement
    company_profile = db.company_profile
    historical = db.historical
    stock_split = db.stock_split
    return balance_sheet_collection, income_collection, cash_collection, company_profile, historical, stock_split


class SECDatabase(MyLogger):
    def __init__(self, connection_string):
        super().__init__(name='SECDatabase', level='DEBUG', log_file='./logs/sec_logs.log')
        self.client = MongoClient(connection_string)
        self.db = self.client.SECRawData
        self.tickerdata = self.db.TickerData
        self.tickerfilings = self.db.TickerFilings
        self.sicdb = self.db.SICList

        try:
            self.tickerdata.create_index([('cik', ASCENDING)])
            self.scrape_logger.info('Created index for cik')
        except Exception as e:
            self.scrape_logger.error(e)

        try:
            self.tickerfilings.create_index([('cik', ASCENDING)])
            self.tickerfilings.create_index([('filings.form', ASCENDING)])
            self.scrape_logger.info('Created index for cik and filing form')
        except Exception as e:
            self.scrape_logger.error(e)

    def get_server_info(self):
        return self.client.server_info()

    def get_collection_names(self):
        return self.db.list_collection_names()

    def get_tickerdata_index_information(self):
        return self.tickerdata.index_information()

    def get_tickerfilings_index_information(self):
        return self.tickerfilings.index_information()
