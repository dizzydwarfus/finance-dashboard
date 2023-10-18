import logging
import requests
import pandas as pd
import json
import xml.etree.ElementTree as ET
from ratelimit import limits, sleep_and_retry
from bs4 import BeautifulSoup
from tqdm import trange
import re
from utils.logger import MyLogger


def convert_keys_to_lowercase(d):
    """Recursively convert all keys in a dictionary to lowercase.

    Args:
        d (dict): Dictionary to convert

    Returns:
        dict: Dictionary with all keys converted to lowercase
    """
    new_dict = {}
    for k, v in d.items():
        if isinstance(v, dict):
            v = convert_keys_to_lowercase(v)
        new_key = re.sub(r'[^a-zA-Z0-9]', '', k.lower())
        new_dict[new_key] = v
    return new_dict


def indexify_url(folder_url: str) -> str:
    """Converts url to index url.

    Args:
        url (str): url to convert to index url

    Returns:
        str: index url
    """
    return folder_url + '/index.json'


class SECData(MyLogger):
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
    SIC_LIST_URL = "https://www.sec.gov/corpfin/division-of-corporation-finance-standard-industrial-classification-sic-code-list"
    US_GAAP_TAXONOMY_URL = "https://xbrl.fasb.org/us-gaap/2023/elts/us-gaap-2023.xsd"
    ALLOWED_TAXONOMIES = ['us-gaap', 'ifrs-full', 'dei', 'srt']
    INDEX_EXTENSION = ['-index.html', '-index-headers.html']
    DIRECTORY_INDEX = ['index.json', 'index.xml', 'index.html']
    FILE_EXTENSIONS = ['.xsd', '.htm', '_cal.xml',
                       '_def.xml', '_lab.xml', '_pre.xml', '_htm.xml', '.xml']

    def __init__(self, requester_company: str = 'Financial API', requester_name: str = 'API Caller', requester_email: str = 'apicaller@gmail.com', taxonomy: str = 'us-gaap',):
        super().__init__(name='sec-scraper', level='debug', log_file='././logs.log')

        self.requester_company = requester_company
        self.requester_name = requester_name
        self.requester_email = requester_email
        self.sec_headers = {"User-Agent": f"{requester_company} {requester_name} {requester_email}",
                            "Accept-Encoding": "gzip, deflate",
                            "Host": "www.sec.gov"}
        self.sec_data_headers = {"User-Agent": f"{requester_company} {requester_name} {requester_email}",
                                 "Accept-Encoding": "gzip, deflate",
                                 "Host": "data.sec.gov"}
        self._cik_list = None
        self._tags = None
        if taxonomy not in self.ALLOWED_TAXONOMIES:
            raise ValueError(
                f"Taxonomy {taxonomy} is not supported. Please use one of the following taxonomies: {self.ALLOWED_TAXONOMIES}")
        self.taxonomy = taxonomy

    @property
    def cik_list(self,):
        if self._cik_list is None:
            self._cik_list = self.get_cik_list()
        return self._cik_list

    @property
    def tags(self,):
        if self._tags is None:
            self._tags = self.get_usgaap_tags()
        return self._tags

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
            self.scrape_logger.error(f'''Request failed at URL: {url}''')
        else:
            self.scrape_logger.info(f'''Request successful at URL: {url}''')
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
        ticker_cik = self.cik_list.query(
            f"ticker == '{ticker.upper()}'")['cik_str']
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

    def get_submissions(self, cik: str = None, submission_file: str = None) -> dict:
        if cik is not None:
            url = f"{self.BASE_API_URL}submissions/CIK{cik}.json"
        elif submission_file is not None:
            url = f"{self.BASE_API_URL}submissions/{submission_file}"
        else:
            raise Exception(
                "Please provide either a CIK number or a submission file.")
        response = self.rate_limited_request(
            url, headers=self.sec_data_headers)
        if response.status_code != 200:
            raise Exception(
                f"Failed to retrieve submissions. Status code: {response.status_code}")
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

    def get_cik_index(self, cik: str = None,) -> dict:
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

    def get_sic_list(self, sic_list_url: str = SIC_LIST_URL) -> dict:
        """Get the list of SIC codes from SEC website.

        Args:
            sic_list_url (str): URL to the list of SIC codes

        Returns:
            pd.DataFrame: DataFrame containing the SIC codes and descriptions
        """
        response = self.rate_limited_request(
            sic_list_url, headers=self.sec_headers)

        soup = BeautifulSoup(response.content, "lxml")
        sic_table = soup.find('table', {'class': 'list'})
        sic_list = []
        for row in sic_table.find_all('tr')[1:]:
            sic_dict = {'_id': None,
                        'Office': None, 'Industry Title': None}
            sic_dict['_id'] = row.text.split('\n')[1]
            sic_dict['Office'] = row.text.split('\n')[2]
            sic_dict['Industry Title'] = row.text.split('\n')[3]
            sic_list.append(sic_dict)

        return sic_list


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
        self._submissions = self.get_submissions(self.cik)
        self._filings = None
        self._forms = None
        self._index = self.get_cik_index(self.cik)
        self._filing_folder_urls = None
        self._filing_urls = None

    @property
    def submissions(self,) -> dict:
        if self._submissions is not None:
            self._submissions['cik'] = self.cik
            self._submissions['filings'] = self.filings.replace(
                {pd.NaT: None}).to_dict('records')
        return self._submissions

    @property
    def filings(self,) -> pd.DataFrame:
        if self._filings is None:
            self._filings = self.get_filings()
        return self._filings

    @property
    def latest_filing(self,) -> pd.DataFrame:
        return self.filings.iloc[0, :].to_dict() if len(self.filings) > 0 else None

    @property
    def latest_10Q(self,) -> pd.DataFrame:
        return self.filings.query("form == '10-Q'").iloc[0, :].to_dict() if len(self.filings.query("form == '10-Q'")) > 0 else None

    @property
    def latest_10K(self,) -> pd.DataFrame:
        return self.filings.query("form == '10-K'").iloc[0, :].to_dict() if len(self.filings.query("form == '10-K'")) > 0 else None

    @property
    def latest_8K(self,) -> pd.DataFrame:
        return self.filings.query("form == '8-K'").iloc[0, :].to_dict() if len(self.filings.query("form == '8-K'")) > 0 else None

    @property
    def filing_folder_urls(self,) -> list:
        if self._filing_folder_urls is None:
            self._filing_folder_urls = self._get_filing_folder_urls()
        return self._filing_folder_urls

    @property
    def filing_urls(self,) -> list:
        if self._filing_urls is None:
            self._filing_urls = self.filings['file_url'].tolist()

        return self._filing_urls

    @property
    def forms(self,) -> list:
        if self._forms is None:
            self._forms = self.filings['form'].unique()
        return self._forms

    def _get_filing_folder_urls(self,) -> list:
        """Get filing folder urls from index dict.

        Args:
            index (dict): index dict from get_index method

        Returns:s
            filing_folder_urls (list): list of filing folder urls
        """

        filing_folder_urls = [self.BASE_SEC_URL + self._index['directory']['name'] + '/' + folder['name']
                              for folder in self._index['directory']['item'] if folder['type'] == 'folder.gif']
        return filing_folder_urls

    def _get_filing_urls(self,) -> list:
        """(DEPRECATED)
        ---The filing urls are implemented in the get_filings method.---

        Get filing urls from filing folder urls.

        Args:
            filing_folder_urls (list): list of filing folder urls

        Returns:
            filing_urls (list): list of filing urls to .txt files
        """
        filing_urls = []
        with trange(len(self.filing_folder_urls), desc=f'Instantiating filing urls for {self.ticker}...') as t:
            for i in t:
                self.scrape_logger.info(t)
                try:
                    soup = self.get_file_data(self.filing_folder_urls[i])
                    for link in soup.find_all('a'):
                        if link.get('href').endswith('.txt'):
                            filing_urls.append(
                                self.BASE_SEC_URL + link.get('href'))
                except Exception as e:
                    self.scrape_logger.error(
                        f'Failed to instantiate filing urls for {self.ticker}...')
                    self.scrape_logger.error(e)
                    t.write(
                        f'Failed to instantiate filing urls for {self.ticker}...')
                    continue
        return filing_urls

    def get_filing_folder_index(self, folder_url: str, return_df: bool = True):
        """Get filing folder index from folder url.

        Args:
            folder_url (str): folder url to retrieve data from
            return_df (bool, optional): Whether to return a DataFrame or dict. Defaults to True.

        Returns:
            index (dict): index dict or dataframe
        """
        index_url = indexify_url(folder_url)
        index = self.rate_limited_request(index_url, headers=self.sec_headers)
        return pd.DataFrame(index.json()['directory']['item']) if return_df else index.json()['directory']['item']

    def get_filings(self,) -> dict:
        """Get filings and urls to .txt from submissions dict.

        Args:
            submissions (dict): submissions dict from get_submissions method

        Returns:
            filings (dict): dictionary containing filings
        """
        self.scrape_logger.info(
            f'Making http request for {self.ticker} filings...')
        filings = self._submissions['filings']['recent']

        if len(self._submissions['filings']) > 1:
            self.scrape_logger.info(
                f'Additional filings found for {self.ticker}...')
            for file in self._submissions['filings']['files']:
                additional_filing = self.get_submissions(
                    submission_file=file['name'])
                filings = {key: filings[key] + additional_filing[key]
                           for key in filings.keys()}

        filings = pd.DataFrame(filings)
        # Convert reportDate, filingDate, acceptanceDateTime columns to datetime
        filings['reportDate'] = pd.to_datetime(filings['reportDate'])
        filings['filingDate'] = pd.to_datetime(filings['filingDate'])
        filings['acceptanceDateTime'] = pd.to_datetime(
            filings['acceptanceDateTime'])
        filings['cik'] = self.cik

        filings = filings.loc[~pd.isnull(filings['reportDate'])]

        # get folder url for each row
        filings['folder_url'] = self.BASE_DIRECTORY_URL + \
            self.cik + '/' + filings['accessionNumber'].str.replace('-', '')

        # get file url for each row
        filings['file_url'] = filings['folder_url'] + \
            '/' + filings['accessionNumber'] + '.txt'

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
        try:
            soup = BeautifulSoup(data.content, "lxml")
            self.scrape_logger.info(
                f'Parsed file data from {file_url} successfully.')
            return soup

        except Exception as e:
            self.scrape_logger.error(
                f'Failed to parse file data from {file_url}. Error: {e}')
            raise Exception(
                f'Failed to parse file data from {file_url}. Error: {e}')

    # TODO: replace search_xxx methods with strategy pattern
    def search_tags(self, soup: BeautifulSoup, pattern: str) -> BeautifulSoup:
        """Search for tags in BeautifulSoup object.

        Args:
            soup (BeautifulSoup): BeautifulSoup object
            pattern (str): regex pattern to search for

        Returns:
            soup: BeautifulSoup object
        """
        return soup.find_all(re.compile(pattern))

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
            temp_dict['contextId'] = tag.attrs.get('id')
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

    def search_linklabels(self, soup: BeautifulSoup) -> pd.DataFrame:
        """Search for link labels in company .txt filing. 
        Link labels provide information about the relationship between facts and their corresponding concepts.

        Args:
            soup (BeautifulSoup): BeautifulSoup object

        Returns:
            df: DataFrame containing link label information with columns 
            {
                'linkLabelId': str,
                'xlinkLabel': str,
                'xlinkRole': str,
                'xlinkType': str,
                'xlmnsXml': str,
                'xmlLang': str,
                'label': str
            }
        """
        links = self.search_tags(soup, '^link:label$')
        dict_list = []
        columns = {'linkLabelId': str, 'xlinkLabel': str, 'xlinkRole': str,
                   'xlinkType': str, 'xlmnsXml': str, 'xmlLang': str, 'label': str}

        for tag in links:
            temp_dict = {}
            temp_dict['linkLabelId'] = tag.attrs.get('id')
            temp_dict['xlinkLabel'] = tag.attrs.get('xlink:label')
            temp_dict['xlinkRole'] = tag.attrs.get('xlink:role')
            temp_dict['xlinkType'] = tag.attrs.get('xlink:type')
            temp_dict['xlmnsXml'] = tag.attrs.get('xmlns:xml')
            temp_dict['xmlLang'] = tag.attrs.get('xml:lang')
            temp_dict['label'] = tag.text if tag.text is not None else None
            dict_list.append(temp_dict)

        df = pd.DataFrame(dict_list, columns=columns.keys()).astype(columns)
        return df

    def search_facts(self, soup: BeautifulSoup) -> pd.DataFrame:
        """Search for facts in company .txt filing. 
        Facts provide the actual data values for the XBRL disclosures.

        Args:
            soup (BeautifulSoup): BeautifulSoup object

        Returns:
            df: DataFrame containing fact information with columns 
            {
                'factName': str,
                'contextRef': str,
                'decimals': int,
                'factId': str,
                'unitRef': str,
                'value': str
            }
        """
        facts = self.search_tags(soup, '^us-gaap:')
        dict_list = []
        columns = {'factName': str, 'contextRef': str, 'decimals': int, 'factId': str,
                   'unitRef': str, 'value': str}

        for tag in facts:
            temp_dict = {}
            temp_dict['factName'] = tag.name
            temp_dict['contextRef'] = tag.attrs.get('contextref')
            temp_dict['decimals'] = tag.attrs.get('decimals')
            temp_dict['factId'] = tag.attrs.get('id')
            temp_dict['unitRef'] = tag.attrs.get('unitref')
            temp_dict['value'] = tag.text
            dict_list.append(temp_dict)

        df = pd.DataFrame(dict_list, columns=columns.keys())
        return df

    def get_metalinks(self, metalinks_url: str) -> pd.DataFrame:
        """Get metalinks from metalinks url.

        Args:
            metalinks_url (str): metalinks url to retrieve data from

        Returns:
            df: DataFrame containing metalinks information with columns 
            {
                'labelKey': str,
                'localName': str,
                'labelName': int,
                'terseLabel': str,
                'documentation': str,
            }
        """
        try:
            response = self.rate_limited_request(
                url=metalinks_url, headers=self.sec_headers).json()
            metalinks_instance = convert_keys_to_lowercase(
                response['instance'])
            instance_key = list(metalinks_instance.keys())[0]
            dict_list = []
            for i in metalinks_instance[instance_key]['tag']:
                dict_list.append(dict(labelKey=i.lower(),
                                      localName=metalinks_instance[instance_key]['tag'][i].get(
                                          'localname'),
                                      labelName=metalinks_instance[instance_key]['tag'][i].get(
                                          'lang').get('enus').get('role').get('label'),
                                      terseLabel=metalinks_instance[instance_key]['tag'][i].get(
                                          'lang').get('enus').get('role').get('terselabel'),
                                      documentation=metalinks_instance[instance_key]['tag'][i].get('lang').get('enus').get('role').get('documentation'),))

            df = pd.DataFrame.from_dict(dict_list)
            return df
        except Exception as e:
            self.scrape_logger.error(
                f'Failed to retrieve metalinks from {metalinks_url}. Error: {e}')
            return None

    def get_facts_for_each_filing(self, filing: dict) -> dict:
        """Get facts for each filing.

        Args:
            filing_url (str): filing url to retrieve data from (link to .txt file in filing directory)
            folder_url (str): folder url to retrieve data from (link to filing directory)
        Returns:
            df: DataFrame containing facts information with columns 
            {
                'factName': str,
                'contextRef': str,
                'decimals': int,
                'factId': str,
                'unitRef': str,
                'value': str,
                'contextId': str,
                'entity': str,
                'segment': str,
                'startDate': 'datetime64[ns]',
                'endDate': 'datetime64[ns]',
                'instant': 'datetime64[ns]',
                'labelKey': str,
                'localName': str,
                'labelName': int,
                'terseLabel': str,
                'documentation': str,
                'accessionNumber': str,
            }
        """
        columns_to_keep = ['factName', 'contextRef', 'decimals', 'factId', 'unitRef', 'value', 'segment', 'startDate',
                           'endDate', 'instant', 'labelKey', 'localName', 'labelName', 'terseLabel', 'documentation', 'accessionNumber']
        soup = self.get_file_data(filing['file_url'])
        facts = self.search_facts(soup)
        context = self.search_context(soup)
        metalinks = self.get_metalinks(
            filing['folder_url'] + '/MetaLinks.json')

        if metalinks is None:
            return None
        context['segment'] = context['segment'].str.replace(
            pat=r'[^a-zA-Z0-9]', repl='', regex=True).str.lower()
        df = facts.merge(context, how='left', left_on='contextRef', right_on='contextId')\
            .merge(metalinks, how='left', left_on='segment', right_on='labelKey')

        df['ticker'] = self.ticker
        df['cik'] = self.cik
        df['accessionNumber'] = filing['accessionNumber']

        df = df.loc[~df['unitRef'].isnull(), columns_to_keep].replace({
            pd.NaT: None})

        return facts, context, metalinks, df.to_dict('records')

    def __repr__(self) -> str:
        class_name = type(self).__name__
        main_attrs = ['ticker', 'cik', 'submissions', 'filings']
        available_methods = [method_name for method_name in dir(self) if callable(
            getattr(self, method_name)) and not method_name.startswith("_")]
        return f"""{class_name}({self.ticker})
    CIK: {self.cik}
    Latest filing: {self.latest_filing['filingDate'].strftime('%Y-%m-%d') if self.latest_filing else 'No filing found'} for Form {self.latest_filing['form'] if self.latest_filing else None}. Access via: {self.latest_filing['folder_url'] if self.latest_filing else None}
    Latest 10-Q: {self.latest_10Q['filingDate'].strftime('%Y-%m-%d') if self.latest_10Q else 'No filing found'}. Access via: {self.latest_10Q['folder_url'] if self.latest_10Q else None}
    Latest 10-K: {self.latest_10K['filingDate'].strftime('%Y-%m-%d') if self.latest_10K else 'No filing found'}. Access via: {self.latest_10K['folder_url'] if self.latest_10K else None}"""

    def __repr_html__(self) -> str:
        class_name = type(self).__name__
        main_attrs = ['ticker', 'cik', 'submissions', 'filings']
        available_methods = [method_name for method_name in dir(self) if callable(
            getattr(self, method_name)) and not method_name.startswith("_")]
        latest_filing_date = self.latest_filing['filingDate'].strftime(
            '%Y-%m-%d') if self.latest_filing else 'No filing found'
        latest_filing_form = self.latest_filing['form'] if self.latest_filing else None
        latest_filing_folder_url = self.latest_filing['folder_url'] if self.latest_filing else None
        latest_10Q_date = self.latest_10Q['filingDate'].strftime(
            '%Y-%m-%d') if self.latest_10Q else 'No filing found'
        latest_10Q_folder_url = self.latest_10Q['folder_url'] if self.latest_10Q else None
        latest_10K_date = self.latest_10K['filingDate'].strftime(
            '%Y-%m-%d') if self.latest_10K else 'No filing found'
        latest_10K_folder_url = self.latest_10K['folder_url'] if self.latest_10K else None
        return f"""
        <div style="border: 1px solid #ccc; padding: 10px; margin: 10px;">
            <h3>{self.submissions['name']}</h3>
            <h5>{self.submissions['sicDescription']}</h5>
            <p><strong>Ticker:</strong> {self.ticker}</p>
            <p><strong>CIK:</strong> {self.cik}</p>
            <p><strong>Latest filing:</strong> {latest_filing_date} for Form {latest_filing_form}. Access via: <a href="{latest_filing_folder_url}">{latest_filing_folder_url}</a></p>
            <p><strong>Latest 10-Q:</strong> {latest_10Q_date}. Access via: <a href="{latest_10Q_folder_url}">{latest_10Q_folder_url}</a></p>
            <p><strong>Latest 10-K:</strong> {latest_10K_date}. Access via: <a href="{latest_10K_folder_url}">{latest_10K_folder_url}</a></p>
        </div>
        """


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
            choice_data = TickerData(ticker=choice)
            choice_data.scrape_logger.info(f"Data saved to {file_name}")
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
