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
        BASE_API_URL (str): Base url for SEC Edgar database
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

    BASE_API_URL = "https://data.sec.gov/"
    US_GAAP_TAXONOMY_URL = "https://xbrl.fasb.org/us-gaap/2023/elts/us-gaap-2023.xsd"
    ALLOWED_TAXONOMIES = ['us-gaap', 'ifrs-full', 'dei', 'srt']
    DIRECTORY_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_number}/{file_name}"
    INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/index.json"

    def __init__(self, requester_company: str, requester_name: str, requester_email: str, taxonomy: str):
        self.requester_company = requester_company
        self.requester_name = requester_name
        self.requester_email = requester_email
        self.sec_headers = {"User-Agent": f"{requester_company} {requester_name} {requester_email}",
                            "Accept-Encoding": "gzip, deflate",
                            "Host": "www.sec.gov"}
        self.sec_data_headers = {"User-Agent": f"{requester_company} {requester_name} {requester_email}",
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

    def get_usgaap_tags(self, xsd_url: str = US_GAAP_TAXONOMY_URL):
        """Get the list of tags (elements) in us-gaap taxonomy or provide a different xsd_url to get tags from a different taxonomy.

        Returns:
            list of tags
        """
        response = requests.get(xsd_url, headers=self.sec_headers)
        xsd_content = response.text
        root = ET.fromstring(xsd_content)

        return [element.attrib['name'] for element in root.findall(".//{http://www.w3.org/2001/XMLSchema}element")]

    @sleep_and_retry
    @limits(calls=10, period=1)
    def get_submissions(self, cik):
        url = f"{self.BASE_API_URL}submissions/CIK{cik}.json"
        response = requests.get(url, headers=self.sec_data_headers)
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
        url = f"{self.BASE_API_URL}api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{tag}.json"
        response = requests.get(url, headers=self.sec_data_headers)
        data = json.loads(response.text)
        return data

    @sleep_and_retry
    @limits(calls=10, period=1)
    def get_company_facts(self, cik):
        url = f"{self.BASE_API_URL}api/xbrl/companyfacts/CIK{cik}.json"
        response = requests.get(url, headers=self.sec_data_headers)
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
        url = f"{self.BASE_API_URL}api/xbrl/frames/{taxonomy}/{tag}/{unit}/{period}.json"
        response = requests.get(url, headers=self.sec_data_headers)
        data = json.loads(response.text)
        return data

    def get_data_as_dataframe(self, cik: str,):
        """Retrieves the XBRL disclosures from a single company (CIK) and returns it as a pandas dataframe.

        Args:
            cik (str): CIK number of the company. Get the list using self.cik

        Returns:
            df: pandas dataframe containing the XBRL disclosures from a single company (CIK)
        """
        data = self.get_company_facts(cik)

        df = pd.DataFrame()

        for tag in data['facts'][self.taxonomy]:
            facts = data['facts']['us-gaap'][tag]['units']
            unit_key = list(facts.keys())[0]
            temp_df = pd.DataFrame(facts[unit_key])
            temp_df['label'] = tag
            df = pd.concat([df, temp_df], axis=0, ignore_index=True)
        df = df.astype({'val': 'float64',
                        'end': 'datetime64[ns]',
                        'start': 'datetime64[ns]',
                        'filed': 'datetime64[ns]'})
        df['Months Ended'] = (df['end'] - df['start']
                              ).dt.days.div(30.4375).round(0)
        return df

    @sleep_and_retry
    @limits(calls=10, period=1)
    def get_cik_index(self, cik: str,):
        """Each CIK directory and all child subdirectories contain three files to assist in 
        automated crawling of these directories. 
        These are not visible through directory browsing.
            - index.html (the web browser would normally receive these)
            - index.xml (a XML structured version of the same content)
            - index.json (a JSON structured vision of the same content)

        Args:
            cik (str): CIK number of the company. Get the list using self.cik

        Returns:
            json: pandas dataframe containing the XBRL disclosures from a single company (CIK)
        """
        url = self.INDEX_URL.format(cik=cik)
        response = requests.get(url, headers=self.sec_headers)
        return response.json()


if __name__ == "__main__":
    sec = SECData(requester_company='Financial Docs', requester_name='John Doe',
                  requester_email='financialdocs@gmail.com', taxonomy='us-gaap')

    # Get user input
    while True:
        ticker = input("Enter ticker: ")
        if ticker in sec.cik['ticker'].values:
            companyfacts = sec.get_data_as_dataframe(
                sec.get_ticker_cik(ticker))
            file_name = f"data/{ticker}.csv"
            companyfacts.to_csv(file_name, index=False)
            print(f"Data saved to {file_name}")
            print('---------------------------------------')

        elif ticker == 'exit':
            exit()
        elif ticker == 'list':
            for row in sec.cik.iterrows():
                print(row[1]['ticker'], row[1]['title'])
            print('---------------------------------------')

        elif ticker.isalpha():
            search_results = sec.cik.loc[sec.cik['title'].str.lower().str.contains(
                ticker)]
            if len(search_results) == 0:
                print("No results found.")
                print('---------------------------------------')
            else:
                print(f"Found {len(search_results)} results:")
                print('---------------------------------------')
                for row in search_results.iterrows():
                    print(f"{row[1]['ticker']}: {row[1]['title']}")
                print('---------------------------------------')

        else:
            print("Invalid ticker. Please try again.")
            print('---------------------------------------')
