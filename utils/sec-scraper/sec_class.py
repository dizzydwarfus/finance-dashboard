import requests
import pandas as pd
import json
import xml.etree.ElementTree as ET
from ratelimit import limits, sleep_and_retry


class SECData:
    """Class to retrieve data from SEC Edgar database.

    Args:
        requester_name (str): Name of the requester
        requester_email (str): Email of the requester
        taxonomy (str): us-gaap, ifrs-full, dei, or srt

    Raises:
        Exception: If taxonomy is not one of the following: us-gaap, ifrs-full, dei, or srt

    Attributes:
        BASE_URL (str): Base url for SEC Edgar database
        US_GAAP_TAXONOMY_URL (str): URL for us-gaap taxonomy
        ALLOWED_TAXONOMIES (list): List of allowed taxonomies
        headers (dict): Headers to be used for API calls
        cik (DataFrame): DataFrame containing CIK and ticker
        tags (list): List of tags in us-gaap taxonomy
        taxonomy (str): us-gaap, ifrs-full, dei, or srt

    Methods:
        get_cik_list: Retrieves the full list of CIK available from SEC database.
        get_ticker_cik: Get a specific ticker's CIK number. 
        get_usgaap_tags: Get the list of tags in us-gaap taxonomy.
        get_submissions: Retrieves the list of submissions for a specific CIK.
        get_company_concept: Retrieves the XBRL disclosures from a single company (CIK) 
            and concept (a taxonomy and tag) into a single JSON file.
        get_company_facts: Retrieves the XBRL disclosures from a single company (CIK) 
            into a single JSON file.
        get_frames: Retrieves one fact for each reporting entity that is last filed that most closely fits the calendrical period requested.
    """

    BASE_URL = "https://data.sec.gov/"
    US_GAAP_TAXONOMY_URL = "https://xbrl.fasb.org/us-gaap/2023/elts/us-gaap-2023.xsd"
    ALLOWED_TAXONOMIES = ['us-gaap', 'ifrs-full', 'dei', 'srt']

    def __init__(self, requester_name: str, requester_email: str, taxonomy: str):
        self.requester_name = requester_name
        self.requester_email = requester_email
        self.headers = {"User-Agent": f"{requester_name} {requester_email}",
                        "Accept-Encoding": "gzip, deflate",
                        "Host": "data.sec.gov"}
        self.cik = self.get_cik_list()
        self.tags = self.get_usgaap_tags()
        if taxonomy not in self.ALLOWED_TAXONOMIES:
            raise Exception(
                f"Taxonomy {taxonomy} is not supported. Please use one of the following taxonomies: {self.ALLOWED_TAXONOMIES}")
        self.taxonomy = taxonomy

    def get_cik_list(self):
        """Retrieves the full list of CIK available from SEC database.

        Raises:
            Exception: On failure to retrieve CIK list

        Returns:
            cik_df: DataFrame containing CIK and ticker
        """
        url = r"https://www.sec.gov/files/company_tickers.json"
        cik_raw = requests.get(url)
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

    def get_usgaap_tags(self,):
        """Get the list of tags in us-gaap taxonomy.

        Returns:
            list of tags
        """
        response = requests.get(self.US_GAAP_TAXONOMY_URL)
        xsd_content = response.text
        root = ET.fromstring(xsd_content)

        return [element.attrib['name'] for element in root.findall(".//{http://www.w3.org/2001/XMLSchema}element")]

    @sleep_and_retry
    @limits(calls=10, period=1)
    def get_submissions(self, cik):
        url = f"{self.BASE_URL}submissions/CIK{cik}.json"
        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            raise Exception(
                f"Failed to retrieve submissions for CIK {cik}. Status code: {response.status_code}")
        data = json.loads(response.text)
        return data

    @sleep_and_retry
    @limits(calls=10, period=1)
    def get_company_concept(self, cik: str, tag: str, taxonomy: str = 'us-gaap',):
        """The company-concept API returns all the XBRL disclosures from a single company (CIK) 
        and concept (a taxonomy and tag) into a single JSON file, with a separate array of facts 
        for each units on measure that the company has chosen to disclose 
        (e.g. net profits reported in U.S. dollars and in Canadian dollars).

        Args:
            cik (str): CIK number of the company. Get the list using self.cik
            taxonomy (str): us-gaap, ifrs-full, dei, or srt
            tag (str): taxonomy tag (e.g. Revenue, AccountsPayableCurrent). See full list from https://xbrl.fasb.org/us-gaap/2023/elts/us-gaap-2023.xsd

        Raises:
            Exception: On failure to retrieve company concept either due to invalid CIK, taxonomy, or tag

        Returns:
            data: JSON file containing all the XBRL disclosures from a single company (CIK)
        """
        url = f"{self.BASE_URL}api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{tag}.json"
        response = requests.get(url, headers=self.headers)
        data = json.loads(response.text)
        return data

    @sleep_and_retry
    @limits(calls=10, period=1)
    def get_company_facts(self, cik):
        url = f"{self.BASE_URL}api/xbrl/companyfacts/CIK{cik}.json"
        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            raise Exception(
                f"Failed to retrieve company facts for CIK {cik}. Status code: {response.status_code}")
        data = json.loads(response.text)
        return data

    @sleep_and_retry
    @limits(calls=10, period=1)
    def get_frames(self, taxonomy, tag, unit, period):
        """The xbrl/frames API aggregates one fact for each reporting entity that is last filed that most closely fits the calendrical period requested. 
        This API supports for annual, quarterly and instantaneous data: https://data.sec.gov/api/xbrl/frames/us-gaap/AccountsPayableCurrent/USD/CY2019Q1I.json

        Args:
            taxonomy (str): us-gaap, ifrs-full, dei, or srt
            tag (str): taxonomy tag (e.g. Revenue, AccountsPayableCurrent). See full list from https://xbrl.fasb.org/us-gaap/2023/elts/us-gaap-2023.xsd
            unit (str): USD, USD-per-shares, etc.
            period (str): CY#### for annual data (duration 365 days +/- 30 days), CY####Q# for quarterly data (duration 91 days +/- 30 days), CY####Q#I for instantaneous data

        Raises:
            Exception: (placeholder)

        Returns:
            data: json formatted response
        """
        url = f"{self.BASE_URL}api/xbrl/frames/{taxonomy}/{tag}/{unit}/{period}.json"
        response = requests.get(url, headers=self.headers)
        data = json.loads(response.text)
        return data
