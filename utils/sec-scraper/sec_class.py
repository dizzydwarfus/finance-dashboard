import requests
import pandas as pd
import json
import xml.etree.ElementTree as ET
from ratelimit import limits, sleep_and_retry
import logging
from bs4 import BeautifulSoup
from tqdm import trange

# Configure the logging settings
logging.basicConfig(level=logging.DEBUG, filename='sec_logs.log',
                    filemode='a', format='%(asctime)s - %(levelname)s - %(message)s')


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
    BASE_SEC_URL = "https://www.sec.gov/"
    BASE_DIRECTORY_URL = "https://www.sec.gov/Archives/edgar/data/"
    US_GAAP_TAXONOMY_URL = "https://xbrl.fasb.org/us-gaap/2023/elts/us-gaap-2023.xsd"
    ALLOWED_TAXONOMIES = ['us-gaap', 'ifrs-full', 'dei', 'srt']
    INDEX_EXTENSION = ['-index.html', '-index-headers.html']
    FILE_EXTENSIONS = ['.xsd', '.htm', '_cal.xml',
                       '_def.xml', '_lab.xml', '_pre.xml', '_htm.xml', '.xml']

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
            raise ValueError(
                f"Taxonomy {taxonomy} is not supported. Please use one of the following taxonomies: {self.ALLOWED_TAXONOMIES}")
        self.taxonomy = taxonomy

    @sleep_and_retry
    @limits(calls=10, period=1)
    def rate_limited_request(self, url: str, headers: dict):
        """Rate limited request to SEC Edgar database.

        Args:
            url (str): URL to retrieve data from
            headers (dict): Headers to be used for API calls

        Returns:
            response: Response from API call
        """
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            logging.error(f'''
Request failed at URL: {url}''')
        return response

    def get_cik_list(self):
        """Retrieves the full list of CIK available from SEC database.

        Raises:
            Exception: On failure to retrieve CIK list

        Returns:
            cik_df: DataFrame containing CIK and ticker
        """
        url = r"https://www.sec.gov/files/company_tickers.json"
        cik_raw = self.rate_limited_request(url, self.sec_headers)
        cik_json = cik_raw.json()
        cik_df = pd.DataFrame.from_dict(cik_json).T
        return cik_df

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
        response = self.rate_limited_request(xsd_url, headers=self.sec_headers)
        xsd_content = response.text
        root = ET.fromstring(xsd_content)

        return [element.attrib['name'] for element in root.findall(".//{http://www.w3.org/2001/XMLSchema}element")]

    def get_submissions(self, cik):
        url = f"{self.BASE_API_URL}submissions/CIK{cik}.json"
        response = self.rate_limited_request(
            url, headers=self.sec_data_headers)
        if response.status_code != 200:
            raise Exception(
                f"Failed to retrieve submissions for CIK {cik}. Status code: {response.status_code}")
        data = json.loads(response.text)
        return data

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
        response = self.rate_limited_request(
            url, headers=self.sec_data_headers)
        data = json.loads(response.text)
        return data

    def get_company_facts(self, cik):
        url = f"{self.BASE_API_URL}api/xbrl/companyfacts/CIK{cik}.json"
        response = self.rate_limited_request(
            url, headers=self.sec_data_headers)
        if response.status_code != 200:
            raise Exception(
                f"Failed to retrieve company facts for CIK {cik}. Status code: {response.status_code}")
        data = json.loads(response.text)
        return data

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
        response = self.rate_limited_request(
            url, headers=self.sec_data_headers)
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

    def get_index(self, cik: str = None,) -> dict:
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
        if cik is not None:
            url = self.BASE_DIRECTORY_URL + cik + '/' + 'index.json'

        else:
            url = self.BASE_DIRECTORY_URL + self.cik + '/' + 'index.json'

        response = self.rate_limited_request(url, headers=self.sec_headers)
        return response.json()


class TickerData(SECData):
    """Inherited from SECData class. Retrieves data from SEC Edgar database based on ticker.
    url is constructed based on the following: https://www.sec.gov/Archives/edgar/data/{cik}/{ascension_number}/{file_name}
    cik is the CIK number of the company = access via get_ticker_cik
    ascension_number is the accessionNumber column of filings_df
    file name for xml is always '{ticker}-{reportDate}.{extension}
    """

    def __init__(self, ticker: str, requester_company: str = 'Financial API', requester_name: str = 'API Caller', requester_email: str = 'apicaller@gmail.com', taxonomy: str = 'us-gaap',):
        super().__init__(requester_company, requester_name, requester_email, taxonomy)
        self.ticker = ticker.upper()
        self.cik = self.get_ticker_cik(self.ticker)
        self._submissions = None
        self._filings = None
        self.forms = self.filings['form'].unique()
        self._index = self.get_index(self.cik)
        self._filing_folder_urls = None
        self._filing_urls = None

    @property
    def submissions(self,) -> dict:
        if self._submissions is None:
            self._submissions = self.get_submissions(self.cik)
        return self._submissions

    @property
    def filings(self,) -> pd.DataFrame:
        if self._filings is None:
            self._filings = self.get_filings(self.submissions)
        return self._filings

    @property
    def filing_folder_urls(self,) -> list:
        if self._filing_folder_urls is None:
            self._filing_folder_urls = self.get_filing_folder_urls()
        return self._filing_folder_urls

    @property
    def filing_urls(self,) -> list:
        if self._filing_urls is None:
            self._filing_urls = self.get_filing_urls()

        return self._filing_urls

    def get_filing_folder_urls(self,) -> list:
        """Get filing folder urls from index dict.

        Args:
            index (dict): index dict from get_index method

        Returns:
            filing_folder_urls (list): list of filing folder urls
        """
        filing_folder_urls = [self.BASE_SEC_URL + self._index['directory']['name'] + '/' + folder['name']
                              for folder in self._index['directory']['item'] if folder['type'] == 'folder.gif']
        return filing_folder_urls

    def get_filing_urls(self,) -> list:
        """Get filing urls from filing folder urls.

        Args:
            filing_folder_urls (list): list of filing folder urls

        Returns:
            filing_urls (list): list of filing urls to .txt files
        """
        filing_urls = []
        with trange(len(self.filing_folder_urls), desc=f'Instantiating filing urls for {self.ticker}...') as t:
            for i in t:
                logging.info(t)
                try:
                    soup = self.get_file_data(self.filing_folder_urls[i])
                    for link in soup.find_all('a'):
                        if link.get('href').endswith('.txt'):
                            filing_urls.append(
                                self.BASE_SEC_URL + link.get('href'))
                except Exception as e:
                    logging.error(
                        f'Failed to instantiate filing urls for {self.ticker}...')
                    logging.error(e)
                    t.write(
                        f'Failed to instantiate filing urls for {self.ticker}...')
                    continue
        return filing_urls

    def get_filings(self, submissions: dict):
        """Get filings from submissions dict.

        Args:
            submissions (dict): submissions dict from get_submissions method

        Returns:
            filings (DataFrame): DataFrame containing filings
        """
        filings = pd.DataFrame(submissions['filings']['recent'])

        # Convert reportDate, filingDate, acceptanceDateTime columns to datetime
        filings['reportDate'] = pd.to_datetime(filings['reportDate'])
        filings['filingDate'] = pd.to_datetime(filings['filingDate'])
        filings['acceptanceDateTime'] = pd.to_datetime(
            filings['acceptanceDateTime'])
        filings['file_url'] = self.BASE_DIRECTORY_URL + self.cik + '/' + \
            filings['accessionNumber'].str.replace(
                '-', '') + '/' + filings['accessionNumber'] + '.txt'
        return filings

    def get_file_data(self, file_url: str) -> BeautifulSoup:
        """Get file data from file url which can be retrieved by calling self.get_file_url method.

        Args:
            file_url (str): File url to retrieve data from on the SEC website

        Returns:
            data: File data as a BeautifulSoup object
        """
        data = self.rate_limited_request(
            url=file_url, headers=self.sec_headers)
        soup = BeautifulSoup(data.content, "lxml")
        return soup

    def search_tags(self, soup: BeautifulSoup, pattern: str) -> BeautifulSoup:
        """Search for tags in BeautifulSoup object.

        Args:
            soup (BeautifulSoup): BeautifulSoup object
            pattern (str): pattern to search for

        Returns:
            soup: BeautifulSoup object
        """
        return soup.find_all(pattern)

    def search_context(self, soup: BeautifulSoup) -> pd.DataFrame:
        """Search for context in company .txt filing. 
        Context provides information about the entity, segment, and time period for facts in the filing.

        Args:
            soup (BeautifulSoup): BeautifulSoup object

        Returns:
            df: DataFrame containing context information with columns 
            {
                'contextId': str,
                'entity': str,
                'segment': str,
                'startDate': 'datetime64[ns]',
                'endDate': 'datetime64[ns]',
                'instant': 'datetime64[ns]'
            }
        """
        contexts = self.search_tags(soup, '^context$')
        dict_list = []
        columns = {'contextId': str, 'entity': str, 'segment': str,
                   'startDate': 'datetime64[ns]', 'endDate': 'datetime64[ns]', 'instant': 'datetime64[ns]'}
        for tag in contexts:
            temp_dict = {}
            temp_dict['contextId'] = tag.attrs['id']
            temp_dict['entity'] = tag.find("entity").text.split()[
                0] if tag.find("entity") is not None else None
            temp_dict['segment'] = tag.find("segment").text.strip(
            ) if tag.find("segment") is not None else None
            temp_dict['startDate'] = tag.find("startdate").text if tag.find(
                "startdate") is not None else None
            temp_dict['endDate'] = tag.find("enddate").text if tag.find(
                "enddate") is not None else None
            temp_dict['instant'] = tag.find("instant").text if tag.find(
                "instant") is not None else None
            dict_list.append(temp_dict)

        df = pd.DataFrame(dict_list, columns=columns.keys()).astype(columns)
        return df


if __name__ == "__main__":
    sec = SECData(requester_company='Financial Docs', requester_name='John Doe',
                  requester_email='financialdocs@gmail.com', taxonomy='us-gaap')

    # Get user input
    while True:
        choice = input(
            """
Choose one of the following options:
- Enter a ticker symbol to get all facts in SEC database
- Enter a company name to search for ticker symbols
- 'list' to list all tickers
- 'exit' to exit

Your input: """)
        if choice in sec.cik['ticker'].values:
            companyfacts = sec.get_data_as_dataframe(
                sec.get_ticker_cik(choice))
            file_name = f"data/{choice}.csv"
            companyfacts.to_csv(file_name, index=False)
            print(f"Data saved to {file_name}")
            print('---------------------------------------')

        elif choice == 'exit':
            exit()
        elif choice == 'list':
            for row in sec.cik.iterrows():
                print(row[1]['ticker'], row[1]['title'])
            print('---------------------------------------')

        elif choice.isalpha():
            search_results = sec.cik.loc[sec.cik['title'].str.lower().str.contains(
                choice)]
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
