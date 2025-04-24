import os
import re
import requests
from PyPDF2 import PdfReader

def extract_title_and_doi(pdf_path):
    reader = PdfReader(pdf_path)
    first_page_text = "".join([
        reader.pages[i].extract_text()
        for i in list(range(min(5, len(reader.pages)))) + list(range(max(0, len(reader.pages)-2), len(reader.pages)))
        if reader.pages[i].extract_text()
    ])
    lines = [line.strip() for line in first_page_text.split('\n') if line.strip()]

    potential_titles = [
        line for line in lines[:40] 
        if not re.search(r"(license|rights|attribution|commons|basin|earthquake|report|prepared|department|university|abstract|publication|figure|table|caption|data)", line, re.IGNORECASE)
        and 5 < len(line.split()) < 25 and line[0].isupper()
    ]
    title = max(potential_titles, key=len) if potential_titles else ""
    # Prefer line above 'By ...' author block if available
    for i in range(1, len(lines)):
        if re.match(r"(?i)^by\s+[A-Z][a-z]+", lines[i]):
            candidate = lines[i-1].strip()
            if len(candidate.split()) > 5 and not re.search(r"(license|copyright|rights|attribution|abstract|figure|table|caption|data)", candidate, re.IGNORECASE):
                title = candidate
                break
    # Force uppercase lines (often real title formatting) to be preferred if long enough
    uppercase_titles = [line for line in potential_titles if line.isupper() and len(line.split()) > 5]
    if uppercase_titles:
        title = max(uppercase_titles, key=len)




    doi_match = re.search(r"10\.\d{4,9}/[\w\-.]+", first_page_text, re.IGNORECASE)
    if not doi_match:
        doi_match = re.search(r"10\.\d{4,9}/[^\s\n]+", first_page_text, re.IGNORECASE)

    doi = None
    if doi_match:
        doi = doi_match.group(0).strip().rstrip('.')
        doi = re.sub(r'[A-Z][a-z]+$', '', doi).strip().rstrip('.')
        doi = re.split(r"(?=www\.|\.com|\.org|\s|\n)", doi)[0].strip().rstrip('.')
        

    print(doi, title)
    return title.strip(), doi, lines, first_page_text

def query_crossref(doi):
    try:
        url = f"https://api.crossref.org/works/{doi}"
        response = requests.get(url)
        if response.status_code == 200:
            metadata = response.json()['message']
            first_author = metadata['author'][0].get('family') or metadata['author'][0].get('name', 'UnknownAuthor').split()[-1]
            year = metadata['issued']['date-parts'][0][0]
            return first_author, str(year)
    except Exception as e:
        print(f"CrossRef query failed for DOI {doi}: {e}")
    return "UnknownAuthor", "UnknownYear"

def query_semantic_scholar(title):
    try:
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {
            'query': title,
            'fields': 'title,authors,year',
            'limit': 1
        }
        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            if 'data' in data and data['data']:
                paper = data['data'][0]
                if paper['authors']:
                    author_info = paper['authors'][0]
                    first_author = author_info.get('lastName') or author_info.get('name', 'UnknownAuthor').split()[-1]
                else:
                    first_author = "UnknownAuthor"
                publication_year = paper.get('year', "UnknownYear")
                return first_author, publication_year
    except Exception as e:
        print(f"Semantic Scholar query failed for title '{title}': {e}")
    return "UnknownAuthor", "UnknownYear"

def fallback_extract_from_text(lines, text):
    name_line_pattern = re.compile(r"(?<![A-Za-z])([A-Z][a-z]+\s+[A-Z][a-z]+(?:,\s+[A-Z][a-z]+\s+[A-Z][a-z]+)*)")
    title_words = set(word.lower() for word in lines[0].split()) if lines else set()
    blacklist = {"access", "open", "authors", "journal", "copyright", "science", "research", "the", "earthquake", "data", "material", "geometry"}

    for line in lines:
        match = name_line_pattern.search(line)
        if match:
            names = match.group(1).split(',')[0].strip().split()
            last_name = names[-1]
            if last_name.lower() not in blacklist and last_name.lower() not in title_words:
                return last_name

    corr_pattern = r"(?i)corresponding author.*?\(([^)]+)\)"
    corr_match = re.search(corr_pattern, text)
    if corr_match:
        name = corr_match.group(1)
        last_name = name.strip().split()[-1]
        if last_name.lower() not in blacklist and last_name.lower() not in title_words:
            return last_name

    return "UnknownAuthor"

def fallback_extract_year(text):
    year_matches = re.findall(r"\b(20\d{2}|19\d{2})\b", text)
    if year_matches:
        return max(year_matches)  # Prefer the most recent year
    return "UnknownYear"

def attempt_extract_citation_info(text):
    match = re.search(r"(?i)Citation:\s+([A-Z][a-z]+).*?\b(20\d{2}|19\d{2})\b", text)
    if match:
        author = match.group(1)
        year = match.group(2)
        return author, year
    return "UnknownAuthor", "UnknownYear"

def rename_pdfs_in_folder(folder_path):
    for filename in os.listdir(folder_path):
        if filename.lower().endswith('.pdf'):
            pdf_path = os.path.join(folder_path, filename)
            title, doi, lines, text = extract_title_and_doi(pdf_path)

            author = "UnknownAuthor"
            year = "UnknownYear"

            if doi:
                author, year = query_crossref(doi)

            if (author == "UnknownAuthor" or year == "UnknownYear") and title:
                temp_author, temp_year = query_semantic_scholar(title)
                if author == "UnknownAuthor":
                    author = temp_author
                if year == "UnknownYear":
                    year = temp_year

            if author == "UnknownAuthor" or year == "UnknownYear":
                fallback_author = fallback_extract_from_text(lines, text)
                fallback_year = fallback_extract_year(text)
                if author == "UnknownAuthor":
                    author = fallback_author
                if year == "UnknownYear":
                    year = fallback_year

            if author == "UnknownAuthor" or year == "UnknownYear":
                citation_author, citation_year = attempt_extract_citation_info(text)
                if author == "UnknownAuthor":
                    author = citation_author
                if year == "UnknownYear":
                    year = citation_year

            new_filename = f"{author}_{year}.pdf"
            new_path = os.path.join(folder_path, new_filename)

            counter = 1
            while os.path.exists(new_path):
                new_filename = f"{author}_{year}_{counter}.pdf"
                new_path = os.path.join(folder_path, new_filename)
                counter += 1

            os.rename(pdf_path, new_path)
            print(f"Renamed '{filename}' to '{new_filename}'\n\n")

folder = "."
rename_pdfs_in_folder(folder)
