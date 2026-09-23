import pandas as pd
import requests
from datetime import datetime, timedelta
import os
import pathlib

# -------------
# CONFIGURATION
# -------------

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"

EOL_PRODUCTS_URL = 'https://endoflife.date/api/v1/products'
EOL_API_BASE = 'https://endoflife.date/api/v1/products/'

REQUEST_TIMEOUT = (5, 8)
WARN_THRESHOLD_DAYS = 30
OUTPUT_CSV_NAME = "EOL_determination.csv"

SOFTWARE_COL_OPTIONS = [
    ('Name', 'Version'),
    ('Title', 'Version'),
    ('Software', 'Version'),
    ('Product Name', 'Version'),
    ('Name', None),
    ('Title', None),
    ('Product Name', None),
]

EOL_COL_OPTIONS = [
    ['EOL Date'],
    ['Certification Expiry'],
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
SOURCE_COL = 'Source_File'
REVIEW_FLAG = '[REVIEW]'
NOT_RESEARCHED = {'Not Researched', '', None, 'NULL', 'null', 'N/A', 'n/a', pd.NA, pd.NaT}


# -------------
# QUERY TOOLS
# -------------

def resolve_path(name: str) -> pathlib.Path:
    return DATA_DIR / name


API_AVAILABLE = True

def check_api_connectivity():
    global API_AVAILABLE
    try:
        r = requests.get(EOL_PRODUCTS_URL, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            API_AVAILABLE = True
            raw_data = r.json()
            products = raw_data.get('result', raw_data.get('products', raw_data.get('data', []))) if isinstance(raw_data, dict) else raw_data
            
            cleaned_products = []
            if isinstance(products, list):
                for p in products:
                    if isinstance(p, str):
                        cleaned_products.append(p.strip().lower())
                    elif isinstance(p, dict):
                        name = p.get('name') or p.get('product') or p.get('id') or p.get('slug')
                        if name:
                            cleaned_products.append(str(name).strip().lower())
            return cleaned_products
    except Exception:
        pass

    API_AVAILABLE = False
    return []

PRODUCTS_LIST = check_api_connectivity()

_PRODUCT_NAME_CACHE = {}
_EOL_DATE_CACHE = {}

def find_product_api_name(name):
    if not name or pd.isna(name):
        return None
    if name in _PRODUCT_NAME_CACHE:
        return _PRODUCT_NAME_CACHE[name]

    normalized = str(name).strip().lower().replace(' ', '-').replace('_', '-')
    result = None
    if normalized in PRODUCTS_LIST:
        result = normalized
    else:
        for product in PRODUCTS_LIST:
            if isinstance(product, str) and (normalized in product or product in normalized):
                result = product
                break

    _PRODUCT_NAME_CACHE[name] = result
    return result


def query_eol_date(product_api_name, version_hint=None):
    global API_AVAILABLE
    if not product_api_name or not API_AVAILABLE:
        return None

    cache_key = (product_api_name, str(version_hint) if version_hint is not None else None)
    if cache_key in _EOL_DATE_CACHE:
        return _EOL_DATE_CACHE[cache_key]

    url = f'{EOL_API_BASE}{product_api_name}'
    result = None
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            releases = data if isinstance(data, list) else data.get('releases', []) if isinstance(data, dict) else []
            
            if version_hint and releases:
                version_str = str(version_hint).strip().lower()
                for release in releases:
                    if isinstance(release, dict):
                        cycle_id = str(release.get('name', release.get('cycle', ''))).lower()
                        if cycle_id and version_str in cycle_id:
                            result = release.get('eolFrom', release.get('eol'))
                            break
            if result is None and releases:
                first = releases[0] if isinstance(releases[0], dict) else {}
                result = first.get('eolFrom', first.get('eol'))
    except Exception:
        API_AVAILABLE = False

    _EOL_DATE_CACHE[cache_key] = result
    return result


def evaluate_date_status(dt):
    today = datetime.now().date()
    warn_date = today + timedelta(days=WARN_THRESHOLD_DAYS)
    if dt < today:
        return 'Y'
    elif dt <= warn_date:
        return 'W'
    else:
        return 'N'


def tag_eol_for_row(row, columns):
    eol_col = columns.get('eol_col')
    eol_val = row.get(eol_col) if eol_col else None
    if eol_val and not (pd.isna(eol_val) or str(eol_val).strip() in NOT_RESEARCHED):
        try:
            eol_dt = pd.to_datetime(eol_val).date()
            return evaluate_date_status(eol_dt), eol_val
        except Exception:
            pass

    software_name = row.get(columns['name_col'])
    product_api = find_product_api_name(software_name) if pd.notna(software_name) else None
    version = row.get(columns.get('version_col')) if columns.get('version_col') else None
    eol_date = query_eol_date(product_api, version) if product_api else None

    if eol_date and eol_date not in ('false', False, '', None):
        try:
            eol_dt = pd.to_datetime(eol_date).date()
            return evaluate_date_status(eol_dt), eol_date
        except Exception:
            pass

    return REVIEW_FLAG, None


# -----------------------------
# Main CSV Processing Routine
# -----------------------------

def process_csv(filepath):
    df = pd.read_csv(filepath, on_bad_lines='warn')
    fname = os.path.basename(filepath)
    fname_lower = fname.lower()
    cols = list(df.columns)

    extracted_rows = []

    if 'cert' in fname_lower:
        # Specifically handles Cert files with Product Name & Certification Expiry
        for idx in range(len(df)):
            row = df.iloc[idx]
            exp_val = row.get('Certification Expiry') if 'Certification Expiry' in row else None
            
            tag = REVIEW_FLAG
            if exp_val and str(exp_val).strip() not in NOT_RESEARCHED:
                try:
                    exp_dt = pd.to_datetime(exp_val).date()
                    tag = evaluate_date_status(exp_dt)
                except Exception:
                    pass

            name_val = row.get('Product Name') if 'Product Name' in row else None
            ver_val = row.get('Version') if 'Version' in row else None

            extracted_rows.append({
                'EOL_Tag': tag,
                'Name': name_val,
                'Version': ver_val,
                'EOL Date': exp_val,
                SOURCE_COL: fname
            })
    else:
        columns = {'name_col': None, 'version_col': None, 'eol_col': None}
        for name_col, version_col in SOFTWARE_COL_OPTIONS:
            if name_col in cols:
                columns['name_col'] = name_col
                columns['version_col'] = version_col if version_col in cols else None
                break

        for opt in EOL_COL_OPTIONS:
            for col in opt:
                if col in cols:
                    columns['eol_col'] = col
                    break
            if columns['eol_col']:
                break

        if not columns['name_col']:
            return None

        for idx, row in df.iterrows():
            tag, eol_dt = tag_eol_for_row(row, columns)
            extracted_rows.append({
                'EOL_Tag': tag,
                'Name': row.get(columns['name_col']),
                'Version': row.get(columns['version_col']) if columns['version_col'] else None,
                'EOL Date': eol_dt,
                SOURCE_COL: fname
            })

    return pd.DataFrame(extracted_rows)


if __name__ == "__main__":
    all_dfs = []
    if DATA_DIR.exists():
        for fname in os.listdir(DATA_DIR):
            if fname.endswith('.csv') and fname != OUTPUT_CSV_NAME:
                processed_df = process_csv(str(DATA_DIR / fname))
                if processed_df is not None and not processed_df.empty:
                    all_dfs.append(processed_df)

        if all_dfs:
            combined_df = pd.concat(all_dfs, ignore_index=True)

            # Sort hierarchy: Y -> W -> N -> [REVIEW]
            tag_order = {'Y': 1, 'W': 2, 'N': 3, REVIEW_FLAG: 4}
            combined_df['_sort_key'] = combined_df[TAG_COL].map(lambda x: tag_order.get(x, 99))

            combined_df = combined_df.sort_values(by=['_sort_key', SOURCE_COL, 'Name']).drop(columns=['_sort_key', SOURCE_COL])

            # Ensure ONLY desired columns exist in the exact required order
            output_cols = ['EOL_Tag', 'Name', 'Version', 'EOL Date']
            combined_df = combined_df[output_cols]

            out_file = SCRIPT_DIR / OUTPUT_CSV_NAME
            
            # Save cleanly without trailing commas or stray columns
            combined_df.to_csv(out_file, index=False)
            print(f"[SUCCESS] Cleaned file written to: {out_file}")