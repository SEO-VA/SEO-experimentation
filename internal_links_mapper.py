import requests
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup
import concurrent.futures
import xml.etree.ElementTree as ET
import pandas as pd
from urllib.parse import urljoin, urlparse
from google.colab import files
import time

# Configuration
TIMEOUT = 10
MAX_WORKERS_SITEMAP = 10
MAX_WORKERS_CRAWL = 20
MAX_PAGES = 1000

# Session setup
session = requests.Session()
adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50)
session.mount('http://', adapter)
session.mount('https://', adapter)

def log(message, level="INFO"):
    """Print formatted log message with timestamp."""
    timestamp = time.strftime("%H:%M:%S")
    icons = {
        "INFO": "ℹ️",
        "SUCCESS": "✅",
        "WARNING": "⚠️",
        "ERROR": "❌",
        "PROGRESS": "🔄",
        "START": "🚀",
        "SEARCH": "🔍",
        "SAVE": "💾"
    }
    icon = icons.get(level, "•")
    print(f"[{timestamp}] {icon} {message}")

def get_sitemap_urls(base_url):
    """Fetch sitemap index and return list of sitemap URLs."""
    sitemap_url = f"{base_url}/wp-sitemap.xml"
    log(f"Fetching sitemap index: {sitemap_url}", "PROGRESS")
    
    try:
        response = requests.get(sitemap_url, timeout=TIMEOUT)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        namespaces = {'sitemap': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        sitemap_urls = [loc.text for loc in root.findall('sitemap:sitemap/sitemap:loc', namespaces)]
        log(f"Found {len(sitemap_urls)} sitemaps in index", "SUCCESS")
        return sitemap_urls
    except requests.exceptions.Timeout:
        log(f"Timeout fetching sitemap (>{TIMEOUT}s)", "ERROR")
        return []
    except requests.exceptions.HTTPError as e:
        log(f"HTTP error fetching sitemap: {e.response.status_code}", "ERROR")
        return []
    except ET.ParseError:
        log("Failed to parse sitemap XML - may not be a WordPress site", "ERROR")
        return []
    except Exception as e:
        log(f"Unexpected error: {type(e).__name__}: {e}", "ERROR")
        return []

def fetch_sitemap_urls(sitemap_urls):
    """Fetch all page URLs from sitemaps."""
    def fetch_sitemap(url):
        try:
            response = requests.get(url, timeout=TIMEOUT)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            namespaces = {'': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            return [loc.text for loc in root.findall('./url/loc', namespaces)]
        except Exception:
            return []

    log(f"Fetching URLs from {len(sitemap_urls)} sitemaps...", "PROGRESS")
    site_urls = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_SITEMAP) as executor:
        future_to_url = {executor.submit(fetch_sitemap, url): url for url in sitemap_urls}
        for i, future in enumerate(concurrent.futures.as_completed(future_to_url), 1):
            urls = future.result()
            site_urls.extend(urls)
            if i % 5 == 0 or i == len(sitemap_urls):
                log(f"Processed {i}/{len(sitemap_urls)} sitemaps ({len(site_urls)} URLs so far)", "PROGRESS")
    
    log(f"Total URLs collected: {len(site_urls)}", "SUCCESS")
    return site_urls

def fetch_and_search(url, target_urls_set):
    """Fetch a page and search for target URLs in article links."""
    try:
        response = session.get(url, timeout=TIMEOUT)
        soup = BeautifulSoup(response.content, 'html.parser')
        article = soup.find('article')
        if not article:
            return {}, False  # No article found
        
        results = {target_url: [] for target_url in target_urls_set}
        links = [(urljoin(url, link.get('href', '')), link.get_text(strip=True)) for link in article.find_all('a')]
        
        found_any = False
        for target_url in target_urls_set:
            for link_url, link_text in links:
                if link_url == target_url:
                    results[target_url].append((url, link_text))
                    found_any = True
        
        return results, found_any
    except Exception:
        return {}, False

def crawl_and_search(site_urls, target_urls):
    """Crawl all site URLs and search for target URLs."""
    original_count = len(site_urls)
    
    if len(site_urls) > MAX_PAGES:
        log(f"Limiting crawl to {MAX_PAGES} pages (found {len(site_urls)} total)", "WARNING")
        site_urls = site_urls[:MAX_PAGES]
    
    target_urls_set = set(target_urls)
    all_matches = {target_url: [] for target_url in target_urls}
    
    log(f"Starting crawl of {len(site_urls)} pages...", "START")
    log("This may take a few minutes depending on site size", "INFO")
    
    completed = 0
    pages_with_article = 0
    total_matches = 0
    start_time = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_CRAWL) as executor:
        futures = {executor.submit(fetch_and_search, url, target_urls_set): url for url in site_urls}
        
        for future in concurrent.futures.as_completed(futures):
            completed += 1
            page_results, found_match = future.result()
            
            if page_results:
                pages_with_article += 1
            
            for target_url, matches in page_results.items():
                if matches:
                    all_matches[target_url].extend(matches)
                    total_matches += len(matches)
                    # Log each match as it's found
                    for source_url, anchor in matches:
                        log(f"Found link! '{anchor}' → {target_url[:50]}...", "SEARCH")
            
            # Progress update every 50 pages or at milestones
            if completed % 50 == 0 or completed == len(site_urls):
                elapsed = time.time() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                remaining = (len(site_urls) - completed) / rate if rate > 0 else 0
                log(f"Progress: {completed}/{len(site_urls)} pages ({completed/len(site_urls)*100:.1f}%) | "
                    f"Matches: {total_matches} | ETA: {remaining:.0f}s", "PROGRESS")
    
    elapsed = time.time() - start_time
    log(f"Crawl complete in {elapsed:.1f} seconds", "SUCCESS")
    log(f"Pages with <article> tag: {pages_with_article}/{len(site_urls)}", "INFO")
    log(f"Total links found: {total_matches}", "INFO")
    
    return all_matches

def save_results(all_matches):
    """Save results to CSV files."""
    log("Saving results...", "SAVE")
    
    for target_url, matches in all_matches.items():
        if matches:
            safe_name = urlparse(target_url).path.replace('/', '_').strip('_') or 'homepage'
            filename = f"internal_links_{safe_name}_{len(matches)}_found.csv"
            
            data = [{'Source URL': url, 'Anchor Text': anchor, 'Target URL': target_url} 
                    for url, anchor in matches]
            df = pd.DataFrame(data)
            df.to_csv(filename, index=False)
            
            log(f"Saved {len(matches)} links for {target_url}", "SUCCESS")
            log(f"Downloading: {filename}", "SAVE")
            files.download(filename)
        else:
            log(f"No internal links found pointing to: {target_url}", "WARNING")

def extract_and_process_base_urls(target_urls):
    """Extract base URLs and fetch all sitemap URLs."""
    base_urls = set()
    for url in target_urls:
        parsed = urlparse(url)
        if not parsed.scheme:
            log(f"Invalid URL (missing http/https): {url}", "ERROR")
            continue
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        base_urls.add(base_url)
    
    if not base_urls:
        log("No valid URLs provided", "ERROR")
        return []
    
    log(f"Processing {len(base_urls)} site(s): {', '.join(base_urls)}", "INFO")
    
    all_sitemap_urls = []
    for base_url in base_urls:
        sitemap_urls = get_sitemap_urls(base_url)
        all_sitemap_urls.extend(sitemap_urls)
    
    if not all_sitemap_urls:
        log("No sitemaps found. Make sure the site uses WordPress (wp-sitemap.xml)", "ERROR")
        return []
    
    return fetch_sitemap_urls(all_sitemap_urls)

def main():
    print("\n" + "="*60)
    print("   🔗 INTERNAL LINKS MAPPER")
    print("   Find all internal links pointing to specific pages")
    print("="*60 + "\n")
    
    log("Ready to start", "START")
    print("\nEnter the full URL(s) of pages you want to find internal links TO.")
    print("Example: https://example.com/target-page/")
    print("For multiple URLs, separate with commas.\n")
    
    target_urls_input = input("Target URL(s): ")
    target_urls = [url.strip() for url in target_urls_input.split(',') if url.strip()]
    
    if not target_urls:
        log("No URLs entered. Exiting.", "ERROR")
        return
    
    print("\n" + "-"*60)
    log(f"Searching for internal links to {len(target_urls)} target URL(s):", "SEARCH")
    for url in target_urls:
        print(f"   • {url}")
    print("-"*60 + "\n")
    
    site_urls = extract_and_process_base_urls(target_urls)
    
    if not site_urls:
        log("No pages found to crawl. Exiting.", "ERROR")
        return
    
    print("\n" + "-"*60)
    all_matches = crawl_and_search(site_urls, target_urls)
    print("-"*60 + "\n")
    
    save_results(all_matches)
    
    print("\n" + "="*60)
    log("All done!", "SUCCESS")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
```

## What's New

| Feature | Description |
|---------|-------------|
| **Timestamped logs** | Every message shows the time `[HH:MM:SS]` |
| **Visual icons** | Different icons for different message types (✅❌⚠️🔄🚀🔍💾) |
| **Progress with ETA** | Shows completion %, matches found, and estimated time remaining |
| **Real-time match alerts** | Logs each link as soon as it's found |
| **Better error messages** | Specific errors for timeout, HTTP errors, XML parsing |
| **Summary stats** | Shows pages with `<article>` tags, total time, total matches |
| **Nice header/footer** | Clear visual separation of the tool |

## Sample Output
```
[14:32:01] 🚀 Searching for internal links to 1 target URL(s):
   • https://example.com/best-casinos/

[14:32:01] 🔄 Fetching sitemap index: https://example.com/wp-sitemap.xml
[14:32:02] ✅ Found 8 sitemaps in index
[14:32:02] 🔄 Fetching URLs from 8 sitemaps...
[14:32:04] 🔄 Processed 8/8 sitemaps (342 URLs so far)
[14:32:04] ✅ Total URLs collected: 342

[14:32:04] 🚀 Starting crawl of 342 pages...
[14:32:15] 🔍 Found link! 'top rated casinos' → https://example.com/best-casinos/...
[14:32:18] 🔄 Progress: 50/342 pages (14.6%) | Matches: 1 | ETA: 45s
[14:32:31] 🔍 Found link! 'our casino guide' → https://example.com/best-casinos/...
...
[14:33:12] ✅ Crawl complete in 68.4 seconds
[14:33:12] ℹ️ Pages with <article> tag: 298/342
[14:33:12] ℹ️ Total links found: 7

[14:33:12] 💾 Saved 7 links for https://example.com/best-casinos/
[14:33:12] 💾 Downloading: internal_links_best-casinos_7_found.csv
