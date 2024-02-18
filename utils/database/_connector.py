# Built-in libraries
import datetime as dt
from typing import List, Literal
import os

# Third party libraries
import streamlit as st
from pymongo import MongoClient, ASCENDING
from pymongo import IndexModel, UpdateOne
from pymongo.errors import OperationFailure

# Internal imports
from utils._logger import MyLogger


@st.cache_resource
def init_connection(secrets_name: str = "mongo"):
    # return MongoClient(**st.secrets[secrets_name])
    return MongoClient(os.getenv("MONGO_HOST"))


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
    return (
        balance_sheet_collection,
        income_collection,
        cash_collection,
        company_profile,
        historical,
        stock_split,
    )


class SECDatabase(MyLogger):
    def __init__(self, connection_string):
        super().__init__(name="SECDatabase", level="DEBUG", log_file="././logs.log")
        self.client = MongoClient(connection_string)
        self.db = self.client.SECRawData
        self.tickerdata = self.db.TickerData
        self.tickerfilings = self.db.TickerFilings
        self.sicdb = self.db.SICList
        self.factsdb = self.db.Facts
        self.labelsdb = self.db.Labels

        try:
            self.tickerdata.create_indexes(
                [IndexModel([("cik", ASCENDING)], unique=True)]
            )
        except OperationFailure as e:
            self.scrape_logger.error(e)

        try:
            self.tickerfilings.create_indexes(
                [
                    IndexModel([("accessionNumber", ASCENDING)], unique=True),
                    IndexModel([("form", ASCENDING)]),
                ]
            )
        except OperationFailure as e:
            self.scrape_logger.error(e)

        try:
            self.factsdb.create_indexes(
                [IndexModel([("factId", ASCENDING)], unique=True)]
            )

        except OperationFailure as e:
            self.scrape_logger.error(e)

    @property
    def get_server_info(self):
        return self.client.server_info()

    @property
    def get_collection_names(self):
        return self.db.list_collection_names()

    @property
    def get_tickerdata_index_information(self):
        return self.tickerdata.index_information()

    @property
    def get_tickerfilings_index_information(self):
        return self.tickerfilings.index_information()

    def get_tickerdata(self, cik: str = None, ticker: str = None):
        if cik is not None:
            return self.tickerdata.find_one({"cik": cik})
        elif ticker is not None:
            return self.tickerdata.find_one({"tickers": ticker.upper()})
        else:
            raise Exception("Please provide either a CIK or ticker.")

    def insert_submission(self, submission: dict):
        """Insert submissions into SEC database. CIK is the primary key.

        Args:
            ticker (TickerData): TickerData object

        Returns:
            str: empty string if successful
            str: ticker's cik if failed
        """
        submission["lastUpdated"] = dt.datetime.now()
        try:
            self.tickerdata.update_one(
                {"cik": submission["cik"]}, {"$set": submission}, upsert=True
            )
            self.scrape_logger.info(
                f'Inserted submissions for {submission["cik"]} into SEC database.'
            )

        except Exception as e:
            self.scrape_logger.error(
                f'Failed to insert submissions for {submission["cik"]} into SEC database. Error: {e}'
            )
            return submission["cik"]
        return None

    def insert_filings(self, cik: str, filings: list):
        """Insert filings into SEC database. Each submission has many filings. Accession number is the primary key.

        Args:
            ticker (TickerData): TickerData object

        Returns:
            str: empty string if successful
            str: ticker's cik if failed
        """
        try:
            for doc in filings:
                doc["lastUpdated"] = dt.datetime.now()

            update_requests = [
                UpdateOne(
                    {"accessionNumber": doc["accessionNumber"]},
                    {"$set": doc},
                    upsert=True,
                )
                for doc in filings
            ]

            self.tickerfilings.bulk_write(update_requests)
            self.scrape_logger.info(f"Sucessfully updated filings for {cik}...")

        except Exception as e:
            self.scrape_logger.error(f"Failed to insert filings for {cik}...{e}")
            return cik
        return None

    def create_update_request(
        self,
        accessionNumber: str,
        items_label: Literal["facts", "labels", "context"],
        items_dict: List[dict],
    ):
        update = UpdateOne(
            {"accessionNumber": accessionNumber},
            {"$set": {items_label: items_dict, "lastUpdated": dt.datetime.now()}},
            upsert=True,
        )
        return update

    def insert_facts(self, accession: str, facts: list):
        """Insert facts into SEC database. Each filing has many facts.

        Args:
            facts (list): A list containing facts for a single filing

        Returns:
            str: empty string if successful
            str: ticker's cik if failed
        """
        try:
            for doc in facts:
                doc["lastUpdated"] = dt.datetime.now()

            fact_update_requests = [
                UpdateOne({"factId": fact["factId"]}, {"$set": fact}, upsert=True)
                for fact in facts
            ]

            self.factsdb.bulk_write(fact_update_requests)
            self.scrape_logger.info(f"Updated facts for {accession}...")

        except Exception as e:
            self.scrape_logger.error(f"Failed to insert facts for {accession}...{e}")
            return accession
        return None
