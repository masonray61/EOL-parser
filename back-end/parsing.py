import pandas as pd
import requests
from datetime import datetime
import os

# -------------
# QUERY TOOLS (Unfinished)
# -------------

def read_csv(file):
    """
    Read csv files and return string
    """
    dataframe = pd.read_csv(file, on_bad_lines='skip')
    print(dataframe)

def write_csv(file):
    """
    Append to a populated csv
    """
    return

def sort_csv(file) -> dict:
    """
    Intention: Take CSVs and store lines with associated data cells
    Return: dictionary with key:values
    """
    return

def match_titles(file):
    return

def resolve_path(name: str):
    # 1. Get the directory of the current script (main.py)
    ROOT_DIR = Path(__file__).resolve().parent.parent

    # 2. Construct the absolute path to test1.csv
    csv_path = ROOT_DIR / "data" / name

    return csv_path

# ------------
# CONFIGURATION
# ------------

# Directory containing the CSV files
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

# Helper to load list of EOL API products for matching
EOL_PRODUCTS_URL = 'https://endoflife.date/api/all.json'
EOL_API_BASE = 'https://endoflife.date/api/'

# Try typical column combos for various CSVs
SOFTWARE_COL_OPTIONS = [
    ['Name', 'Version'],
    ['Title', 'Version'],
    ['Software', 'Version'],
    ['Name'],
    ['Title'],
]

EOL_COL_OPTIONS = [
    ['EOL Date'],
    ['EOL'],
    ['EndOfLife'],
    ['EOL_Tag'],
]

SUITE_COL_OPTIONS = [
    ['Suite Name', 'Suite Version'],
    ['Suite'],
    ['Family'],
]

TAG_COL = 'EOL_Tag'
REVIEW_FLAG = '[REVIEW]'
NOT_RESEARCHED = {'Not Researched', '', None, 'NULL', 'null', 'N/A', 'n/a', pd.NA, pd.NaT}

# ----------
# API helpers
# ----------
def get_eol_products():
    try:
        r = requests.get(EOL_PRODUCTS_URL, timeout=8)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []

PRODUCTS_LIST = get_eol_products()


def find_product_api_name(name):
    """Attempt to map a software/suite name to endoflife.date API product string."""
    if not name:
        return None
    normalized = name.strip().lower().replace(' ', '-').replace('_', '-')
    for product in PRODUCTS_LIST:
        if normalized == product:
            return product
    # Fuzzy match (basic)
    for product in PRODUCTS_LIST:
        if normalized in product or product in normalized:
            return product
    return None


def query_eol_date(product_api_name, version_hint=None):
    """Query the endoflife.date API for the EOL date of a product/cycle/version."""
    if not product_api_name:
        return None
    url = f'{EOL_API_BASE}{product_api_name}.json'
    try:
        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            return None
        data = r.json()
        
        # If version_hint/cycle present, try to best-match
        if version_hint:
            version_str = str(version_hint).strip().lower()
            for cycle in data:
                if 'cycle' in cycle and version_str in str(cycle['cycle']).lower():
                    return cycle.get('eol', None)
        # Fallback: just return EOL of latest
        if data:
            return data[0].get('eol', None)
    except Exception:
        return None
    return None

# -----------------
# Main row tagging
# -----------------

def tag_eol_for_row(row, columns):
    today = datetime.now().date()

    #------ EOL Date Check ------#
    eol_col = columns.get('eol_col')
    eol_val = None
    if eol_col:
        eol_val = row.get(eol_col)
        if pd.isna(eol_val) or str(eol_val).strip() in NOT_RESEARCHED:
            eol_val = None
    
    # If valid EOL date present, tag directly
    if eol_val:
        try:
            eol_dt = pd.to_datetime(eol_val).date()
            return 'Y' if eol_dt < today else 'N'
        except Exception:
            # Not a parseable date? Continue with API lookup
            pass
    #------ API Lookup for Software ------#
    software_name = row.get(columns['name_col'])
    version = row.get(columns.get('version_col', ''))
    product_api = find_product_api_name(software_name)
    eol_date = query_eol_date(product_api, version) if product_api else None

    if eol_date and eol_date not in ('false', False, '', None):
        try:
            eol_dt = pd.to_datetime(eol_date).date()
            return 'Y' if eol_dt < today else 'N'
        except Exception:
            pass
    #------ API Lookup for Suite ------#
    for suite_group in SUITE_COL_OPTIONS:
        suite_name = row.get(suite_group[0]) if suite_group[0] in row else None
        suite_version = None
        if len(suite_group) > 1 and suite_group[1] in row:
            suite_version = row.get(suite_group[1])
        if suite_name:
            suite_api = find_product_api_name(suite_name)
            suite_eol_date = query_eol_date(suite_api, suite_version) if suite_api else None
            if suite_eol_date and suite_eol_date not in ('false', False, '', None):
                try:
                    eol_dt = pd.to_datetime(suite_eol_date).date()
                    return 'Y' if eol_dt < today else 'N'
                except Exception:
                    pass
    #------ Not found, flag for review ------#
    return REVIEW_FLAG

# -----------------------------
# Main CSV Processing Routine
# -----------------------------
def process_csv(filepath):
    print(f"\n--- Processing {filepath} ---")
    
    df = pd.read_csv(filepath)
    cols = list(df.columns)
    # Determine key column set
    columns = {'name_col': None, 'version_col': None, 'eol_col': None}
    for opt in SOFTWARE_COL_OPTIONS:
        for col in opt:
            if not columns['name_col'] and col in cols:
                columns['name_col'] = col
            elif not columns['version_col'] and col in cols:
                columns['version_col'] = col
    for opt in EOL_COL_OPTIONS:
        for col in opt:
            if col in cols:
                columns['eol_col'] = col
                break
        if columns['eol_col']:
            break
    if not columns['name_col']:
        print(f"No valid software name column found in {filepath}")
        return
    # Add EOL_Tag column if missing
    if TAG_COL not in df.columns:
        df[TAG_COL] = None
    # Process each row
    for idx, row in df.iterrows():
        df.at[idx, TAG_COL] = tag_eol_for_row(row, columns)
    # Save output
    out_path = filepath.replace('.csv', '.eol-tagged.csv')
    df.to_csv(out_path, index=False)
    print(f"Updated CSV written to: {out_path}")

if __name__ == "__main__":
    read_csv(resolve_path('Unclass-software.csv'))
    read_csv(resolve_path('Cert-data.csv'))
    read_csv(resolve_path('battle-lab-SW.csv'))
    for fname in os.listdir(DATA_DIR):
        if fname.endswith('.csv'):
            process_csv(os.path.join(DATA_DIR, fname))

