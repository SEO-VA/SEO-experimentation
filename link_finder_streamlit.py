import requests
from bs4 import BeautifulSoup
import concurrent.futures
import re
import pandas as pd
from urllib.parse import urlparse, urljoin
import xml.etree.ElementTree as ET
import streamlit as st

# Functions remain mostly unchanged, except where noted below
def get_sitemap_urls(base_url):
    sitemap_url = f"{base_url}/wp-sitemap.xml"
    try:
        response = requests.get(sitemap_url)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        namespaces = {'sitemap': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        return [loc.text for loc in root.findall('sitemap:sitemap/sitemap:loc', namespaces)]
    except Exception as e:
        st.error(f"Failed to fetch sitemap index: {e}")
        return []

def fetch_sitemap_urls(sitemap_urls):
    def fetch_sitemap(url):
        try:
            response = requests.get(url)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            namespaces = {'': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            return [url.text for url in root.findall('./url/loc', namespaces)]
        except Exception as e:
            st.error(f"Failed to fetch sitemap: {e}")
            return []

    site_urls = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_url = {executor.submit(fetch_sitemap, url): url for url in sitemap_urls}
        for future in concurrent.futures.as_completed(future_to_url):
            site_urls.extend(future.result())
    return site_urls

def find_keywords_in_text(text, keywords):
    matched_sentences = {}
    for keyword in keywords:
        keyword_regex = re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)
        sentences = [sentence.strip() for sentence in re.findall(r'[^.!?]*' + keyword_regex.pattern + r'[^.!?]*[.!?]', text, flags=re.IGNORECASE)]
        if sentences:
            matched_sentences[keyword] = sentences
    return matched_sentences

def fetch_and_search(url, target_url, keywords):
    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.content, 'html.parser')
        parsed_base_url = urlparse(url)
        base_url = f"{parsed_base_url.scheme}://{parsed_base_url.netloc}"
        links_to_check = [urljoin(base_url, link.get('href', '')) for link in soup.select('article p a') if link.get('href', '').startswith('/')]
        if target_url in links_to_check:
            return {'url': url, 'reason': 'contains_target_link'}
        text = ' '.join(p.get_text() for p in soup.select('article p'))
        matched_sentences = find_keywords_in_text(text, keywords)
        if matched_sentences:
            return {'url': url, 'matched_sentences': matched_sentences}
        else:
            return {'url': url, 'reason': 'no_keywords_found'}
    except Exception as e:
        return {'url': url, 'reason': 'fetch_error'}

def crawl_and_search(site_urls, target_url, keywords):
    matches = {}
    skipped_urls = []
    no_keyword_urls = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(fetch_and_search, url, target_url, keywords) for url in site_urls]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                if 'matched_sentences' in result:
                    matches[result['url']] = result['matched_sentences']
                elif result.get('reason') == 'contains_target_link':
                    skipped_urls.append(result['url'])
                elif result.get('reason') == 'no_keywords_found':
                    no_keyword_urls.append(result['url'])
    return matches

# Streamlit app
st.title("Internal Link Finder")

# User input
base_url = st.text_input("Enter the homepage URL of the site:")
target_url = st.text_input("Enter the URL of the page you're adding internal links to:")
keywords_input = st.text_area("Enter keywords to search for (separated by commas):")

if st.button("Find Links"):
    if base_url and target_url and keywords_input:
        keywords = [keyword.strip() for keyword in keywords_input.split(',')]
        sitemap_urls = get_sitemap_urls(base_url)
        site_urls = fetch_sitemap_urls(sitemap_urls)
        site_urls = [url for url in site_urls if url != target_url]
        matches = crawl_and_search(site_urls, target_url, keywords)
        if matches:
            # Save results to CSV
            data = []
            for url, keyword_matches in matches.items():
                for keyword, sentences in keyword_matches.items():
                    row = {'URL': url, 'Keyword': keyword}
                    row.update({f'Sentence {i+1}': sentence for i, sentence in enumerate(sentences)})
                    data.append(row)
            df = pd.DataFrame(data)
            csv = df.to_csv(index=False)
            st.download_button("Download Results", data=csv, file_name="results.csv", mime="text/csv")
        else:
            st.info("No matches found.")
    else:
        st.warning("Please fill out all fields.")
