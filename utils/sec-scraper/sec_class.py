import requests
import pandas as pd
import json


class SECData:
    BASE_URL = "https://data.sec.gov/"

    def __init__(self, requester_name, requester_email):
        self.requester_name = requester_name
        self.requester_email = requester_email
        self.headers = {"User-Agent": f"{requester_name} {requester_email}",
                        "Accept-Encoding": "gzip, deflate",
                        "Host": "data.sec.gov"}
        self.cik = self.get_cik_list()

    def get_submissions(self, cik):

        url = f"{self.BASE_URL}submissions/CIK{cik}.json"
        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            raise Exception(
                f"Failed to retrieve submissions for CIK {cik}. Status code: {response.status_code}")
        data = json.loads(response.text)
        return data

    def get_company_concept(self, cik: str, taxonomy: str, tag: str):
        """The company-concept API returns all the XBRL disclosures from a single company (CIK) 
        and concept (a taxonomy and tag) into a single JSON file, with a separate array of facts 
        for each units on measure that the company has chosen to disclose 
        (e.g. net profits reported in U.S. dollars and in Canadian dollars).

        Args:
            cik (str): CIK number of the company. Get the list using self.cik
            taxonomy (str): us-gaap, ifrs-full, dei, or srt
            tag (str): financial metric tag (e.g. Revenue, AccountsPayableCurrent)

        Raises:
            Exception: On failure to retrieve company concept either due to invalid CIK, taxonomy, or tag

        Returns:
            data: JSON file containing all the XBRL disclosures from a single company (CIK)
        """        ''''''
        url = f"{self.BASE_URL}api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{tag}.json"
        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            raise Exception(
                f"Failed to retrieve company concept for CIK {cik}, taxonomy {taxonomy}, tag {tag}. Status code: {response.status_code}")
        data = json.loads(response.text)
        return data

    def get_company_facts(self, cik):
        url = f"{self.BASE_URL}api/xbrl/companyfacts/CIK{cik}.json"
        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            raise Exception(
                f"Failed to retrieve company facts for CIK {cik}. Status code: {response.status_code}")
        data = json.loads(response.text)
        return data

    def get_frames(self, taxonomy, tag, unit, period):
        url = f"{self.BASE_URL}api/xbrl/frames/{taxonomy}/{tag}/{unit}/{period}.json"
        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            raise Exception(
                f"Failed to retrieve frames for taxonomy {taxonomy}, tag {tag}, unit {unit}, period {period}. Status code: {response.status_code}")
        data = json.loads(response.text)
        return data

    def get_cik_list(self):
        """Retrieves the full list of CIK available from SEC database.

        Raises:
            Exception: On failure to retrieve CIK list

        Returns:
            cik_df: DataFrame containing CIK and ticker
        """
        url = r"https://www.sec.gov/files/company_tickers.json"
        cik_raw = requests.get(url)
        if cik_raw.status_code != 200:
            raise Exception(
                f"Failed to retrieve CIK list. Status code: {cik_raw.status_code}")
        cik_json = cik_raw.json()
        cik_df = pd.DataFrame.from_dict(cik_json).T
        return cik_df

    # Get specific ticker's CIK number
    def get_ticker_cik(self, ticker: str,):
        """Get a specific ticker's CIK number. 
        CIK########## is the entity's 10-digit Central Index Key (CIK).

        Args:
            ticker (str): public ticker symbol of the company

        Returns:
            cik: CIK number of the company excluding the leading 'CIK'
        """
        ticker_cik = self.cik.query(f"ticker == '{ticker}'")['cik_str']
        cik = f"{ticker_cik.iloc[0]:010d}"
        return cik
