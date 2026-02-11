import requests
from bs4 import BeautifulSoup
import concurrent.futures
import re
import csv
import xml.etree.ElementTree as ET
import pandas as pd
from google.colab import files
from urllib.parse import urlparse, urljoin

def get_sitemap_urls(base_url):
    sitemap_url = f"{base_url}/wp-sitemap.xml"
    try:
        response = requests.get(sitemap_url)
        response.raise_for_status()  # This will raise HTTPError for bad responses

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

        # Parse the base URL to extract components
        parsed_base_url = urlparse(url)
        base_url = f"{parsed_base_url.scheme}://{parsed_base_url.netloc}"

        # Check for exact match of target URL and construct full URLs for root-relative links
        links_to_check = []
        for link in soup.select('article p a'):
            href = link.get('href', '')
            if href.startswith('/'):  # Root-relative link
                full_url = urljoin(base_url, href)
                links_to_check.append(full_url)
            else:
                links_to_check.append(href)

        if target_url in links_to_check:
            print(f"URL skipped (contains target link): {url}")
            return {'url': url, 'reason': 'contains_target_link'}

        text = ' '.join(p.get_text() for p in soup.select('article p'))
        matched_sentences = find_keywords_in_text(text, keywords)
        if matched_sentences:
            print(f"Keywords found in URL: {url}")
            return {'url': url, 'matched_sentences': matched_sentences}
        else:
            print(f"No matching keywords found in URL: {url}")
            return {'url': url, 'reason': 'no_keywords_found'}
    except Exception as e:
        print(f"Failed to fetch or search page: {e}")
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

    # Optionally log or handle skipped_urls and no_keyword_urls as needed
    print(f"Skipped URLs (contains target link): {len(skipped_urls)}")
    print(f"URLs with no matching keywords: {len(no_keyword_urls)}")
    return matches


def save_results(matches, output_file_path):
    data = []
    for url, keyword_matches in matches.items():
        for keyword, sentences in keyword_matches.items():
            if sentences:  # Include URL only if there are sentences reported
                row = {'URL': url, 'Keyword': keyword}
                row.update({f'Sentence {i+1}': sentence for i, sentence in enumerate(sentences)})
                data.append(row)

    df = pd.DataFrame(data)
    df.to_csv(output_file_path, index=False)
    print(f"Results saved to {output_file_path}")

    # Trigger download in Google Colab
    files.download(output_file_path)

def main():
    base_url = input("Enter the homepage URL of the site: ")
    target_url = input("Enter the URL of the page you're adding internal links to: ")
    keywords_input = input("Enter the keywords to search for (separated by commas): ")
    keywords = [keyword.strip() for keyword in keywords_input.split(',')]

    sitemap_urls = get_sitemap_urls(base_url)
    site_urls = fetch_sitemap_urls(sitemap_urls)

     # Exclude the target_url from the list of site URLs
    site_urls = [url for url in site_urls if url != target_url]

    output_file_path = "results.csv"

    matches = crawl_and_search(site_urls, target_url, keywords)
    if matches:
        save_results(matches, output_file_path)
    else:
        print("No matches found or all pages contain the target link. No CSV generated.")

if __name__ == "__main__":
    main()
