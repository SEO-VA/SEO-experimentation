import requests
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup
import concurrent.futures
import xml.etree.ElementTree as ET
import pandas as pd
from urllib.parse import urljoin, urlparse
from google.colab import files
import os

# Configuration
TIMEOUT = 10  # seconds
MAX_WORKERS_SITEMAP = 10
MAX_WORKERS_CRAWL = 20
MAX_PAGES = 500  # Limit to prevent endless crawling

# Session with customized adapter settings
session = requests.Session()
adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50)
session.mount('http://', adapter)
session.mount('https://', adapter)

def get_sitemap_urls(base_url):
    """Fetch sitemap index and return list of sitemap URLs."""
    sitemap_url = f"{base_url}/wp-sitemap.xml"
    print(f"Fetching sitemap index: {sitemap_url}")
    try:
        response = requests.get(sitemap_url, timeout=TIMEOUT)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        namespaces = {'sitemap': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        sitemap_urls = [loc.text for loc in root.findall('sitemap:sitemap/sitemap:loc', namespaces)]
        print(f"  Found {len(sitemap_urls)} sitemaps")
        return sitemap_urls
    except Exception as e:
        print(f"  Failed: {e}")
        return []

def fetch_sitemap_urls(sitemap_urls):
    """Fetch all page URLs from sitemaps."""
    def fetch_sitemap(url):
        try:
            response = requests.get(url, timeout=TIMEOUT)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            namespaces = {'': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            urls = [loc.text for loc in root.findall('./url/loc', namespaces)]
            return urls
        except Exception as e:
            print(f"  Failed to fetch sitemap {url}: {e}")
            return []

    site_urls = []
    print(f"Fetching URLs from {len(sitemap_urls)} sitemaps...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_SITEMAP) as executor:
        future_to_url = {executor.submit(fetch_sitemap, url): url for url in sitemap_urls}
        for future in concurrent.futures.as_completed(future_to_url):
            urls = future.result()
            site_urls.extend(urls)
    
    print(f"Total URLs found: {len(site_urls)}")
    return site_urls

def fetch_and_search(url, target_urls_set):
    """Fetch a page and search for target URLs in article links."""
    try:
        response = session.get(url, timeout=TIMEOUT)
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
        return {}

def crawl_and_search(site_urls, target_urls):
    """Crawl all site URLs and search for target URLs."""
    # Limit pages to prevent endless crawling
    if len(site_urls) > MAX_PAGES:
        print(f"⚠️  Limiting crawl to {MAX_PAGES} pages (found {len(site_urls)})")
        site_urls = site_urls[:MAX_PAGES]
    
    target_urls_set = set(target_urls)
    all_matches = {target_url: [] for target_url in target_urls}
    
    print(f"Crawling {len(site_urls)} pages...")
    completed = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_CRAWL) as executor:
        futures = {executor.submit(fetch_and_search, url, target_urls_set): url for url in site_urls}
        for future in concurrent.futures.as_completed(futures):
            completed += 1
            if completed % 50 == 0:
                print(f"  Progress: {completed}/{len(site_urls)} pages crawled")
            
            page_results = future.result()
            for target_url, matches in page_results.items():
                all_matches[target_url].extend(matches)
    
    print(f"Crawling complete!")
    return all_matches

def save_results(all_matches):
    """Save results to CSV files."""
    for target_url, matches in all_matches.items():
        if matches:
            filename = f"results_{urlparse(target_url).netloc}_{len(matches)}_links.csv"
            filename = filename.replace('/', '_').replace('?', '_').replace('&', '_')
            data = [{'Source URL': url, 'Anchor Text': anchor} for url, anchor in matches]
            df = pd.DataFrame(data)
            df.to_csv(filename, index=False)
            print(f"✅ Found {len(matches)} links to {target_url}")
            print(f"   Saved to {filename}")
            files.download(filename)
        else:
            print(f"❌ No links found to {target_url}")

def extract_and_process_base_urls(target_urls):
    """Extract base URLs and fetch all sitemap URLs."""
    base_urls = set()
    for url in target_urls:
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        base_urls.add(base_url)
    
    print(f"Processing {len(base_urls)} site(s): {base_urls}")
    
    all_sitemap_urls = []
    for base_url in base_urls:
        sitemap_urls = get_sitemap_urls(base_url)
        all_sitemap_urls.extend(sitemap_urls)
    
    return fetch_sitemap_urls(all_sitemap_urls)

def main():
    target_urls_input = input("Enter the URLs of the pages you're looking for links to, separated by a comma: ")
    target_urls = [url.strip() for url in target_urls_input.split(',')]
    
    print(f"\n🔍 Searching for links to: {target_urls}\n")
    
    site_urls = extract_and_process_base_urls(target_urls)
    
    if not site_urls:
        print("❌ No URLs found in sitemaps. Check if the site uses wp-sitemap.xml")
        return
    
    all_matches = crawl_and_search(site_urls, target_urls)
    save_results(all_matches)

if __name__ == "__main__":
    main()
