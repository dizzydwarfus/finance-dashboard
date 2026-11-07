# Documentation of Scraping SEC.gov
The purpose of this document is two-fold:
1. Elaborate on the reasons of scraping for financial data
3. Lessons learned along the way

## Table of Contents

- [Documentation of Scraping SEC.gov](#documentation-of-scraping-secgov)
  - [Table of Contents](#table-of-contents)
  - [Why self-scrape?](#why-self-scrape)
  - [Data Sources and Tools](#data-sources-and-tools)
  - [Lessons Learned](#lessons-learned)


## Why self-scrape?

There are loads of ready-made APIs out there that serve as secondary distributors of company financial information. I have personally used some of them from [Alpha Vantage](https://www.alphavantage.co/documentation/) and [Financial Modeling Prep](https://site.financialmodelingprep.com/). Using these APIs on its free-of-charge basis provides sufficient financial information for basic analysis on a company's financial health. Despite limitation on number of requests per day, I have never once hit the ceiling limit. However, much of the information that is needed to deep-dive into a company's financials are held behind paywalls. Therefore, I have decided to go to the source itself for these information, [U.S. Securities and Exchange Commission](www.sec.gov). Below I summarized the advantages and disadvantages of doing so:

| Advantages                                                                                                                           | Disadvantages                                                     |
| ------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------- |
| Licensing only limited by SEC.gov <br>(summary can be found here [SEC Data Privacy and Security](https://www.sec.gov/privacy#intro)) | Unable to use for distribution as freely <br>(API dependent)      |
| Unlimited number of requests per day <br>(only limited by requests per second)                                                       | Limited to some number of requests per day by <br>API distributor |
| Data always kept up-to-date                                                                                                          | Data may not be latest information available                      |
| Most reliable source of public financial information                                                                                 | Dependent on how data is extracted and processed by API creator   |
| Difficult to interpret - requires lots of cleaning and processing from HTML/XML/XBRL formats                                         | Readily available in JSON/csv/table format for interpretation     |
| Only company filings available                                                                                                       | Market/Analyst/Macro-economic data are also available             |
| Free                                                                                                                                 | Free with paid-services available                                 |


## Data Sources and Tools

The main core part of the financial data obtained will be from [Data SEC](www.sec.gov). Several open-source tools/libraries may be used when needed to aid in scraping these data. These tools include but not limited to:

1. requests
2. BeautifulSoup
3. Pandas


## Lessons Learned
| Topic | Lesson                                                                                                                                                                                                                                                                                                        |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1     | SEC Provides a programmatic way to scrape data from their website via [SEC Edgar API](https://www.sec.gov/edgar/sec-api-documentation)                                                                                                                                                                        |
| 2     | The API has multiple endpoints:submissions, companyconcept, facts, frames. These endpoints provide a way to scrape the high level detail (such as Net Income, Net Debt, etc without breakdown into individual product or geographic segments). For the further details, scraping the actual filing is needed. |
| 3     | There is a directory crawling method to be able to find all files pertaining to any and all filings by a company.                                                                                                                                                                                             |
| 4     | A structure of Ticker -> Submissions -> Filings would fit very well in a document database. Then the TickerData class in sec_class.py can be used to make HTTP requests to each of the filing URL. The filing URL lead to a .txt file where it is a culmination of all documents in the filing directory.     |
| 5     | Beautiful Soup can be used to parse the HTML and XML documents.                                                                                                                                                                                                                                               |
| 6     | SEC filings are submitted based on XBRL, which was first introduced in 2005 (voluntary basis), made mandatory in 2009. After June 28, 2018, the Commission adopted amendments requiring the use (phased in) of inline XBRL.                                                                                   |
| 7     | XBRL tags that correspond to Commission financial statement and schedule disclosure requirements are available in the 2018 SEC Reporting taxonomy ("SRT") and the 2018 U.S. Generally Accepted Accounting Principles (U.S. GAAP) Taxonomy, these exists in the XBRL documents as **<<us-gaap:xxxxxx>>**.      |
| 8     | SECData and TickerData class that I have written works on some companies but not all. BeautifulSoup ".text", ".string" attributes, and ".get_text()" method do not work on some companies' filings.                                                                                                           |
| 9     | MongoDB supports max document size of 16MB, which leads to separate storage of company submissions and company filings, and facts for each filing is also stored in a separate collection.                                                                                                                    |
| 10    | Accession Number is a unique number assigned to each digital submission document. This can be used to identify any filing made.                                                                                                                                                                               |
| 11    | **MetaLinks.json** did not exist for filings before 2018. Only tested the scraping method on the top 10 tickers. Need to use regular HTML tables scraping for filings before 2018.                                                                                                                            |
| 12    | Filings from 2009 H2 onwards have .xml files that can be parse using xml standard library in python, bs4 works too.                                                                                                                                                                                           |
| 13    | Combination of the xml files (_lab, _def, _cal, _pre) give context to the filing.                                    Mainly _lab, _def, and _cal. _pre is less important.                                                                                                                                     |
| 14    | Taking a new approach to limit number of requests from SEC Edgar where I will store top 50 CIK along with filing information into MongoDB and use queries to get filing information instead.                                                                                                                  |
|15|Redesigned how segments for each context of facts are parsed. Before: segment with multiple depth levels will be limited to only the first level, now all levels are represented. Levels are joined to form a single string so the column can remain a string and not a list.|
|16|Storing raw scraping facts/context/labels in mongodb and transformed data in another collection. These will be queried to reduce runtime CPU usage, and not having to make request constantly to SEC.gov.|
|17|Tested deployment to Azure App Service (ASP F1 Plan - Free) - successful|