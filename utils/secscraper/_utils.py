# Third-party libraries
import pandas as pd
import numpy as np
import datetime as dt
import streamlit as st

# Internal imports
from utils.secscraper.sec_class import TickerData
from utils.secscraper._dataclasses import Context, Facts, LinkLabels


def reverse_standard_mapping(standard_name_mapping: dict):
    reverse_mapping = {}
    for standard_name, xbrl_tags in standard_name_mapping.items():
        for tag in xbrl_tags:
            reverse_mapping[tag] = standard_name

    return reverse_mapping


def get_filing_facts(ticker: TickerData, filings_to_scrape: list, verbose=False):
    """
    Scrape facts, context, labels, definitions, calculations, metalinks from filings_to_scrape

    ### Parameters
    ----------
    ticker : TickerData
        TickerData object
    filings_to_scrape : list
        list of filings dict to scrape

    ### Returns
    -------
    all_labels : pd.DataFrame
        all labels scraped
    all_calc : pd.DataFrame
        all calculations scraped
    all_defn : pd.DataFrame
        all definitions scraped
    all_context : pd.DataFrame
        all contexts scraped
    all_facts : pd.DataFrame
        all facts scraped
    all_metalinks : pd.DataFrame    
        all metalinks scraped
    all_merged_facts : pd.DataFrame
        all merged facts scraped
    failed_folders : list
        list of failed folders
    """
    all_labels = pd.DataFrame()
    all_calc = pd.DataFrame()
    all_defn = pd.DataFrame()
    all_context = pd.DataFrame()
    all_facts = pd.DataFrame()
    all_metalinks = pd.DataFrame()
    all_merged_facts = pd.DataFrame()
    failed_folders = []
    fact_update_requests = []

    for file in filings_to_scrape:
        if (file.get('form') != '10-Q' or file.get('form') != '10-K') and file.get('filingDate') < dt.datetime(2009, 1, 1):
            continue

        accessionNumber = file.get('accessionNumber')
        folder_url = file.get('folder_url')
        file_url = file.get('file_url')
        ticker.scrape_logger.info(
            file.get('filingDate').strftime('%Y-%m-%d') + ': ' + folder_url)

        soup = ticker.get_file_data(file_url=file_url)

        try:  # Scrape facts
            facts_list = []
            facts = ticker.search_facts(soup=soup)
            for fact_tag in facts:
                facts_list.append(Facts(fact_tag=fact_tag).to_dict())
            facts_df = pd.DataFrame(facts_list)

            facts_df['accessionNumber'] = accessionNumber
            all_facts = pd.concat([all_facts, facts_df], ignore_index=True)
        except Exception as e:
            ticker.scrape_logger.error(
                f'Failed to scrape facts for {folder_url}...{e}')
            failed_folders.append(dict(folder_url=folder_url, accessionNumber=accessionNumber,
                                  error=f'Failed to scrape facts for {folder_url}...{e}', filingDate=file.get('filingDate')))
            pass

        if len(facts_list) == 0:
            ticker.scrape_logger.info(
                f'No facts found for {ticker.ticker}({ticker.cik})-{folder_url}...\n')
            continue

        try:  # Scrape context
            context_list = []
            contexts = ticker.search_context(soup=soup)
            for tag in contexts:
                context_list.append(Context(context_tag=tag).to_dict())
            context_df = pd.DataFrame(context_list)
            context_df['accessionNumber'] = accessionNumber
            all_context = pd.concat(
                [all_context, context_df], ignore_index=True)
        except Exception as e:
            ticker.scrape_logger.error(
                f'Failed to scrape context for {folder_url}...{e}')
            failed_folders.append(dict(folder_url=folder_url, accessionNumber=accessionNumber,
                                  error=f'Failed to scrape context for {folder_url}...{e}', filingDate=file.get('filingDate')))
            pass

        index_df = ticker.get_filing_folder_index(folder_url=folder_url)

        try:  # Scrape metalinks
            metalinks = ticker.get_metalinks(
                folder_url=folder_url + '/MetaLinks.json')
            metalinks['accessionNumber'] = accessionNumber
            all_metalinks = pd.concat(
                [all_metalinks, metalinks], ignore_index=True)
        except Exception as e:
            ticker.scrape_logger.error(
                f'Failed to scrape metalinks for {folder_url}...{e}')
            failed_folders.append(dict(folder_url=folder_url, accessionNumber=accessionNumber,
                                  error=f'Failed to scrape metalinks for {folder_url}...{e}', filingDate=file.get('filingDate')))
            pass

        try:  # Scrape labels
            labels = ticker.get_elements(folder_url=folder_url, index_df=index_df,
                                         scrape_file_extension='_lab').query("`xlink:type` == 'resource'")
            labels['xlink:role'] = labels['xlink:role'].str.split(
                '/').apply(lambda x: x[-1])
            labels['xlink:labelOriginal'] = labels['xlink:label']
            labels['xlink:label'] = labels['xlink:label']\
                .str.replace('(lab_)|(_en-US)', '', regex=True)\
                    .str.split('_')\
                        .apply(lambda x: ':'.join(x[:2]))\
                .str.lower()
            labels['accessionNumber'] = accessionNumber
            all_labels = pd.concat([all_labels, labels], ignore_index=True)

        except Exception as e:
            ticker.scrape_logger.error(
                f'Failed to scrape labels for {folder_url}...{e}')
            failed_folders.append(dict(folder_url=folder_url, accessionNumber=accessionNumber,
                                  error=f'Failed to scrape labels for {folder_url}...{e}', filingDate=file.get('filingDate')))
            pass

        try:  # Scrape calculations
            calc = ticker.get_elements(folder_url=folder_url, index_df=index_df,
                                       scrape_file_extension='_cal').query("`xlink:type` == 'arc'")
            calc['accessionNumber'] = accessionNumber
            all_calc = pd.concat([all_calc, calc], ignore_index=True)
        except Exception as e:
            ticker.scrape_logger.error(
                f'Failed to scrape calc for {folder_url}...{e}')
            failed_folders.append(dict(folder_url=folder_url, accessionNumber=accessionNumber,
                                  error=f'Failed to scrape calc for {folder_url}...{e}', filingDate=file.get('filingDate')))
            pass

        try:  # Scrape definitions
            defn = ticker.get_elements(folder_url=folder_url, index_df=index_df,
                                       scrape_file_extension='_def').query("`xlink:type` == 'arc'")
            defn['accessionNumber'] = accessionNumber
            all_defn = pd.concat([all_defn, defn], ignore_index=True)
        except Exception as e:
            ticker.scrape_logger.error(
                f'Failed to scrape defn for {folder_url}...{e}')
            failed_folders.append(dict(folder_url=folder_url, accessionNumber=accessionNumber,
                                  error=f'Failed to scrape defn for {folder_url}...{e}', filingDate=file.get('filingDate')))
            pass

        ticker.scrape_logger.info(
            f'Merging facts with context and labels. Current facts length: {len(facts_list)}...')
        try:
            merged_facts = facts_df.merge(context_df, how='left', left_on='contextRef', right_on='contextId')\
                .merge(labels.query("`xlink:role` == 'label'"), how='left', left_on='factName', right_on='xlink:label')
            merged_facts = merged_facts.drop(
                ['accessionNumber_x', 'accessionNumber_y'], axis=1)

            ticker.scrape_logger.info(
                f'Successfully merged facts with context and labels. Merged facts length: {len(merged_facts)}...')
        except Exception as e:
            ticker.scrape_logger.error(
                f'Failed to merge facts with context and labels for {folder_url}...{e}')
            failed_folders.append(dict(folder_url=folder_url, accessionNumber=accessionNumber,
                                  error=f'Failed to merge facts with context and labels for {folder_url}...{e}', filingDate=file.get('filingDate')))
            pass

        all_merged_facts = pd.concat(
            [all_merged_facts, merged_facts], ignore_index=True)

        ticker.scrape_logger.info(
            f'Successfully scraped {ticker.ticker}({ticker.cik})-{folder_url}...\n')
        if verbose:
            st.success(
                ticker.ticker + ' ' + file.get('filingDate').strftime('%Y-%m-%d'))

    all_merged_facts = all_merged_facts.loc[~all_merged_facts['labelText'].isnull(), [
        'labelText', 'segment', 'startDate', 'endDate', 'instant', 'factValue', 'unitRef']]

    return all_labels, all_calc, all_defn, all_context, all_facts, all_metalinks, all_merged_facts, failed_folders


def translate_labels_to_standard_names(merged_facts: pd.DataFrame, standard_name_mapping: dict):
    merged_facts['standardName'] = merged_facts['labelText'].apply(
        lambda x: standard_name_mapping.get(x, x))

    return merged_facts


def clean_values_in_facts(merged_facts: pd.DataFrame):
    df = merged_facts.loc[
        (merged_facts['factValue'].str.contains(
            '^-?\d+(\.\d+)?$'))
        & (merged_facts['factValue'] != "")
        & (merged_facts['factValue'] != "-")
    ].copy()

    df['factValue'] = df['factValue'].astype(float)

    return df


def segment_breakdown_levels(final_df: pd.DataFrame) -> int:
    dict_len = 0
    for i in final_df['segment']:
        if isinstance(i, dict):
            curr_len = len(list(i.items()))
            if curr_len > dict_len:
                dict_len = curr_len
                if curr_len > 1:
                    print(list(i.items()))

    return dict_len


def clean_values_in_segment(merged_facts: pd.DataFrame, labels_df: pd.DataFrame) -> pd.DataFrame:
    """Segment column of merged facts is cleaned to remove "ticker:" and "us-gaap:" prepend, and to split camel case into separate words (e.g. "us-gaap:RevenuesBeforeTax" becomes "Revenues Before Tax"). 

    Args:
        merged_facts (pd.DataFrame): merged facts data frame from get_filing_facts.

    Returns:
        merged_facts (pd.DataFrame): merged facts data frame with segment column cleaned
    """
    merged_facts['segmentAxis'] = merged_facts['segment']\
        .apply(lambda x: list(x.keys())[0] if isinstance(x, dict) else "")\
        .str.lower()\
        # .apply(lambda x: x.split(':')[1] if x != "" else "")\
    # .str.replace(pat=r'([A-Z])', repl=r' \1', regex=True).str.strip()

    merged_facts['segmentValue'] = merged_facts['segment']\
        .apply(lambda x: list(x.values())[0] if isinstance(x, dict) else "")\
        .str.lower()\
        # .apply(lambda x: x.split(':')[1] if x.find(':') >= 0 else "")\
    # .str.replace(pat=r'([A-Z])', repl=r' \1', regex=True).str.strip()

    merged_facts.drop('segment', axis=1, inplace=True)

    # Merge with labels to get standard names for segment labels
    labels_df = labels_df.query("`xlink:role` == 'label'")[
        ['xlink:label', 'labelText']]
    merged_facts = merged_facts.merge(labels_df, how='left', left_on='segmentAxis', right_on='xlink:label', suffixes=('', '_segmentAxis'))\
        .merge(labels_df, how='left', left_on='segmentValue', right_on='xlink:label', suffixes=('', '_segmentValue'))

    # Fill in missing labelText values with segmentValue
    merged_facts['labelText_segmentValue'].fillna(
        merged_facts['segmentValue'], inplace=True)
    merged_facts.drop(['segmentAxis', 'segmentValue', 'xlink:label',
                      'xlink:label_segmentValue'], axis=1, inplace=True)

    return merged_facts


def split_facts_into_start_instant(merged_facts: pd.DataFrame):
    """Splits facts into start/end and instant

    Args:
        merged_facts (pd.DataFrame): merged facts data frame from get_filing_facts

    Returns:
        merged_facts: merged facts data frame without duplicates on the columns labelText, segment, startDate, endDate, instant, value
        start_end: start/end facts data frame where startDate and endDate are not null
        instant: instant facts data frame where instant is not null
    """
    merged_facts.drop_duplicates(subset=[
        'labelText', 'segment', 'startDate', 'endDate', 'instant', 'factValue'], keep='last', inplace=True)

    start_end = merged_facts.dropna(axis=0, subset=['startDate', 'endDate'])[['labelText', 'segment', 'unitRef',
                                                                              'startDate', 'endDate', 'factValue']].sort_values(by=['labelText', 'segment', 'startDate', 'endDate',])
    instant = merged_facts.dropna(axis=0, subset=['instant'])[
        ['labelText', 'segment', 'unitRef', 'instant', 'factValue']].sort_values(by=['labelText', 'segment', 'instant',])

    return merged_facts, start_end, instant


def get_monthly_period(df: pd.DataFrame) -> pd.DataFrame:
    df['period'] = pd.to_timedelta(
        df['endDate'] - df['startDate']).dt.days / 30.25
    df['period'] = df['period'].round(0)
    df['Months Ended'] = np.select(
        [
            df['period'] == 3,
            df['period'] == 6,
            df['period'] == 9,
            df['period'] == 12,
        ],
        [
            "Three Months Ended",
            "Six Months Ended",
            "Nine Months Ended",
            "Twelve Months Ended",
        ],
        default=None
    )
    return df
