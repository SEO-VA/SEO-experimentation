import requests
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup
import concurrent.futures
import xml.etree.ElementTree as ET
import pandas as pd
from urllib.parse import urljoin
from google.colab import files
import os

# Session with customized adapter settings for improved performance
session = requests.Session()
adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50)
session.mount('http://', adapter)
session.mount('https://', adapter)

def get_sitemap_urls(base_url):
    sitemap_url = f"{base_url}/wp-sitemap.xml"
    try:
        response = requests.get(sitemap_url)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        namespaces = {'sitemap': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        sitemap_urls = [loc.text for loc in root.findall('sitemap:sitemap/sitemap:loc', namespaces)]
        return sitemap_urls
    except Exception as e:
        print(f"Failed to fetch or parse sitemap index: {e}")
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
            print(f"Failed to fetch or parse sitemap: {e}")
            return []

    site_urls = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_url = {executor.submit(fetch_sitemap, url): url for url in sitemap_urls}
        for future in concurrent.futures.as_completed(future_to_url):
            site_urls.extend(future.result())
    return site_urls

def fetch_and_search(url, target_urls_set):
    try:
        response = session.get(url)
        soup = BeautifulSoup(response.content, 'html.parser')
        article = soup.find('article')
        if not article:
            return {}

        results = {target_url: [] for target_url in target_urls_set}
        links = [(urljoin(url, link.get('href', '')), link.get_text(strip=True)) for link in article.find_all('a')]

        for target_url in target_urls_set:
            for link_url, link_text in links:
                if link_url == target_url:
                    results[target_url].append((url, link_text))

        return results
    except Exception as e:
        print(f"Failed to fetch or search page: {e}")
        return {}


def crawl_and_search(site_urls, target_urls):
    target_urls_set = set(target_urls)  # Convert the list to a set for O(1) look-up time
    all_matches = {target_url: [] for target_url in target_urls}
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(fetch_and_search, url, target_urls_set) for url in site_urls]
        for future in concurrent.futures.as_completed(futures):
            page_results = future.result()
            for target_url, matches in page_results.items():
                all_matches[target_url].extend(matches)
    return all_matches

def save_results(all_matches):
    for target_url, matches in all_matches.items():
        if matches:
            filename = f"results_{target_url.split('//')[-1].replace('/', '_').replace('?', '_').replace('&', '_')}.csv"
            data = [{'URL': url, 'Anchor Text': anchor} for url, anchor in matches]
            df = pd.DataFrame(data)
            df.to_csv(filename, index=False, header=False)
            print(f"Results saved to {filename}")
            files.download(filename)
        else:
            print(f"No links to {target_url} were found within the article tags.")

def main():
    base_url = input("Enter the homepage URL of the site: ")
    target_urls_input = input("Enter the URLs of the pages you're looking for links to, separated by a comma: ")
    target_urls = [url.strip() for url in target_urls_input.split(',')]
    sitemap_urls = get_sitemap_urls(base_url)
    site_urls = fetch_sitemap_urls(sitemap_urls)

    all_matches = crawl_and_search(site_urls, target_urls)
    save_results(all_matches)

if __name__ == "__main__":
    main()
