import csv
import os
import re
import pathlib
from datetime import datetime, timedelta

import pandas as pd
import requests

# -------------
# CONFIGURATION
# -------------

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
OUTPUT_DIR = DATA_DIR
PARSED_SUFFIX = "-parsed"

EOL_PRODUCTS_URL = 'https://endoflife.date/api/v1/products'
EOL_API_BASE = 'https://endoflife.date/api/v1/products/'

REQUEST_TIMEOUT = (5, 8)
WARN_MONTHS = 3
MAX_CONSECUTIVE_API_FAILURES = 3
MIN_PARTIAL_MATCH_CHARS = 4

# Certification data file
CERT_DATA_FILE = 'Cert-data.csv'

# EOS Report file pattern - will match any month
EOS_REPORT_PATTERN = r'EOS_Report.*\.xlsx?$'

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
    'EOL Date',
    'Certification Expiry',
    'EOL',
    'EndOfLife',
    'EOS Date',  # Added for EOS Report
]

NOTE_COL_OPTIONS = ['EOL Details', 'Link']

ADD_AUDIT_COLS = True
BASE_COLS = ['EOL_Tag', 'Name', 'Version', 'EOL Date']
OUTPUT_COLS = BASE_COLS + (['Source', 'Note'] if ADD_AUDIT_COLS else [])

TAG_EXPIRED = 'Y'
TAG_WARN = 'W'
TAG_OK = 'N'
TAG_REVIEW = '[REVIEW]'

TAG_SORT_ORDER = {TAG_EXPIRED: 0, TAG_REVIEW: 1, TAG_WARN: 2, TAG_OK: 3}

ADD_SECTION_HEADERS = True
SECTION_HEADERS = [
    ('------- EXPIRED / NO DATA (REVIEW) -------', {TAG_EXPIRED, TAG_REVIEW}),
    (f'------- ABOUT TO EXPIRE (within {WARN_MONTHS} months) -------', {TAG_WARN}),
    ('------- NOT EXPIRING SOON -------', {TAG_OK}),
]

BLANK_STRINGS = {'', 'not researched', 'null', 'none', 'n/a', 'na', 'nan', 'false', 'unknown'}

VENDOR_WORDS = {'microsoft', 'google', 'mozilla', 'oracle', 'adobe', 'apache', 'the',
                'amazon', 'vmware', 'omnissa', 'citrix', 'dell', 'intel', 'nvidia'}

ALIASES = [
    (r'\.net (core |runtime|sdk|host|hosting|desktop|windows)|netcore|aspnetcore|windows desktop runtime', 'dotnet'),
    (r'\.net framework', 'dotnetfx'),
]

NO_PARTIAL_SLUGS = {'bootstrap', 'android', 'express', 'windows', 'office'}

TODAY = pd.Timestamp.today().normalize()
WARN_DATE = TODAY + pd.DateOffset(months=WARN_MONTHS)

# Global lookup dictionaries
CERT_LOOKUP = {}
EOS_LOOKUP = {}


# -------------
# HELPERS
# -------------

def is_blank(value):
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() in BLANK_STRINGS


def parse_date(value):
    """Return a normalized Timestamp, or None if the value isn't a usable date."""
    if is_blank(value):
        return None
    ts = pd.to_datetime(str(value).strip(), errors='coerce')
    if pd.isna(ts):
        return None
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts.normalize()


def evaluate_date_status(dt):
    if dt < TODAY:
        return TAG_EXPIRED
    if dt <= WARN_DATE:
        return TAG_WARN
    return TAG_OK


def normalize_product_name(name):
    """Normalize product name for matching."""
    if is_blank(name):
        return ''
    # Convert to lowercase and remove extra whitespace
    normalized = ' '.join(str(name).lower().split())
    # Remove version numbers and common suffixes
    normalized = re.sub(r'\s+v?\d+(\.\d+)*\s*$', '', normalized)
    normalized = re.sub(r'\s+version\s+\d+(\.\d+)*\s*$', '', normalized)
    return normalized.strip()


def extract_version(name, version_col):
    """Extract version from name or version column."""
    if not is_blank(version_col):
        return str(version_col).strip()
    
    # Try to extract version from name
    if not is_blank(name):
        # Look for version patterns like "v1.2", "2019", "2.x", etc.
        version_match = re.search(r'v?(\d+(?:\.\d+)*(?:\.x)?)', str(name), re.IGNORECASE)
        if version_match:
            return version_match.group(1)
    
    return None


def find_eos_report():
    """Find the EOS report file dynamically, regardless of month in filename."""
    for path in DATA_DIR.glob('*.xlsx'):
        if re.search(EOS_REPORT_PATTERN, path.name, re.IGNORECASE):
            return path
    for path in DATA_DIR.glob('*.xls'):
        if re.search(EOS_REPORT_PATTERN, path.name, re.IGNORECASE):
            return path
    return None


def load_eos_report():
    """Load EOS report data into a lookup dictionary."""
    global EOS_LOOKUP
    
    eos_file = find_eos_report()
    
    if eos_file is None:
        print("[WARN] EOS Report file not found (looking for pattern: EOS_Report*.xlsx)")
        return
    
    print(f"[INFO] Found EOS Report: {eos_file.name}")
    
    try:
        # Try reading Excel file, ALWAYS skip the first row (title row)
        try:
            df = pd.read_excel(eos_file, dtype=str, header=1)  # Row 2 is the header
        except Exception as e:
            print(f"[WARN] Could not read as Excel: {e}")
            print("[INFO] Please install openpyxl: pip install openpyxl")
            return
        
        # Print available columns for debugging
        print(f"[DEBUG] Available columns in EOS Report: {list(df.columns)}")
        
        # Look for vendor and product columns
        vendor_col = None
        product_col = None
        version_col = None
        eos_date_col = None
        extended_eos_col = None
        link_col = None
        
        for col in df.columns:
            col_lower = str(col).lower().strip()
            
            # Vendor column
            if vendor_col is None and 'vendor' in col_lower:
                vendor_col = col
                print(f"[DEBUG] Found vendor column: '{col}'")
            
            # Product column
            if product_col is None and 'product' in col_lower:
                product_col = col
                print(f"[DEBUG] Found product column: '{col}'")
            
            # Version column
            if version_col is None and 'version' in col_lower:
                version_col = col
                print(f"[DEBUG] Found version column: '{col}'")
            
            # Extended EOS column
            if extended_eos_col is None and 'extended' in col_lower:
                extended_eos_col = col
                print(f"[DEBUG] Found extended EOS column: '{col}'")
            
            # EOS Date column
            if eos_date_col is None and 'eos date' in col_lower:
                eos_date_col = col
                print(f"[DEBUG] Found EOS date column: '{col}'")
            
            # Link column
            if link_col is None and 'link' in col_lower:
                link_col = col
                print(f"[DEBUG] Found link column: '{col}'")
        
        if not product_col:
            print("[ERROR] Could not find Product Name column in EOS Report")
            print(f"[ERROR] Available columns are: {', '.join(df.columns)}")
            print("[ERROR] Please ensure your Excel file has a column named 'Product Name' or similar")
            return
        
        print(f"[INFO] Using columns - Product: '{product_col}', Version: '{version_col}', EOS Date: '{eos_date_col}'")
        
        # Process rows
        loaded_count = 0
        for _, row in df.iterrows():
            vendor = row.get(vendor_col) if vendor_col else None
            product_name = row.get(product_col)
            version = row.get(version_col) if version_col else None
            eos_date = row.get(eos_date_col) if eos_date_col else None
            extended_eos = row.get(extended_eos_col) if extended_eos_col else None
            link = row.get(link_col) if link_col else None
            
            if is_blank(product_name):
                continue
            
            # Create lookup key with vendor if available
            if not is_blank(vendor):
                full_name = f"{vendor} {product_name}"
            else:
                full_name = str(product_name)
            
            normalized_name = normalize_product_name(full_name)
            
            # Parse EOS dates
            eos_dt = parse_date(eos_date)
            extended_eos_dt = parse_date(extended_eos)
            
            # Use extended EOS date if available and later
            final_eos_dt = extended_eos_dt if extended_eos_dt else eos_dt
            
            # Create lookup entry
            lookup_key = normalized_name
            if not is_blank(version):
                lookup_key = f"{normalized_name}|{str(version).strip()}"
            
            EOS_LOOKUP[lookup_key] = {
                'vendor': str(vendor).strip() if not is_blank(vendor) else None,
                'product': str(product_name).strip(),
                'version': str(version).strip() if not is_blank(version) else None,
                'eos_date': final_eos_dt,
                'eos_raw': str(eos_date).strip() if not is_blank(eos_date) else None,
                'extended_eos_raw': str(extended_eos).strip() if not is_blank(extended_eos) else None,
                'link': str(link).strip() if not is_blank(link) else None,
                'original_name': full_name
            }
            
            # Also add without version for partial matching
            if not is_blank(version):
                EOS_LOOKUP.setdefault(normalized_name, EOS_LOOKUP[lookup_key])
            
            loaded_count += 1
        
        print(f"[INFO] Loaded {loaded_count} EOS records from {eos_file.name}")
    
    except Exception as e:
        print(f"[ERROR] Failed to load EOS report: {e}")
        import traceback
        traceback.print_exc()


def lookup_eos_report(name, version=None):
    """Look up EOS date from the EOS report."""
    if not EOS_LOOKUP:
        return None
    
    normalized_name = normalize_product_name(name)
    
    # Try exact match with version
    if not is_blank(version):
        lookup_key = f"{normalized_name}|{str(version).strip()}"
        if lookup_key in EOS_LOOKUP:
            eos_data = EOS_LOOKUP[lookup_key]
            if eos_data['eos_date'] is not None:
                source_parts = [f"EOS Report: {eos_data['original_name']}"]
                if eos_data['version']:
                    source_parts.append(f"v{eos_data['version']}")
                return (
                    evaluate_date_status(eos_data['eos_date']),
                    eos_data['extended_eos_raw'] or eos_data['eos_raw'],
                    eos_data['eos_date'],
                    ' '.join(source_parts)
                )
    
    # Try match without version
    if normalized_name in EOS_LOOKUP:
        eos_data = EOS_LOOKUP[normalized_name]
        if eos_data['eos_date'] is not None:
            return (
                evaluate_date_status(eos_data['eos_date']),
                eos_data['extended_eos_raw'] or eos_data['eos_raw'],
                eos_data['eos_date'],
                f"EOS Report: {eos_data['original_name']}"
            )
    
    # Partial match - check if any EOS product name is contained in the search name
    for eos_key, eos_data in EOS_LOOKUP.items():
        eos_normalized = eos_key.split('|')[0]  # Remove version from key
        if eos_normalized in normalized_name or normalized_name in eos_normalized:
            if eos_data['eos_date'] is not None:
                return (
                    evaluate_date_status(eos_data['eos_date']),
                    eos_data['extended_eos_raw'] or eos_data['eos_raw'],
                    eos_data['eos_date'],
                    f"EOS Report (partial match): {eos_data['original_name']}"
                )
    
    return None


def load_cert_data():
    """Load certification data into a lookup dictionary."""
    global CERT_LOOKUP
    cert_file = DATA_DIR / CERT_DATA_FILE
    
    if not cert_file.exists():
        print(f"[WARN] Certification data file not found: {cert_file}")
        return
    
    try:
        df = read_csv_safely(cert_file)
        
        for _, row in df.iterrows():
            product_name = row.get('Product Name')
            cert_expiry = row.get('Certification Expiry')
            date_certified = row.get('Date Certified')
            
            if is_blank(product_name):
                continue
            
            normalized_name = normalize_product_name(product_name)
            
            # Parse certification expiry date
            expiry_date = parse_date(cert_expiry)
            certified_date = parse_date(date_certified)
            
            # Store in lookup dictionary
            CERT_LOOKUP[normalized_name] = {
                'original_name': str(product_name).strip(),
                'expiry_date': expiry_date,
                'certified_date': certified_date,
                'expiry_raw': str(cert_expiry).strip() if not is_blank(cert_expiry) else None,
                'certified_raw': str(date_certified).strip() if not is_blank(date_certified) else None
            }
        
        print(f"[INFO] Loaded {len(CERT_LOOKUP)} certification records from {CERT_DATA_FILE}")
    
    except Exception as e:
        print(f"[ERROR] Failed to load certification data: {e}")


def lookup_cert_expiry(name, version=None):
    """Look up certification expiry for a product."""
    if not CERT_LOOKUP:
        return None
    
    normalized_name = normalize_product_name(name)
    
    # Direct match
    if normalized_name in CERT_LOOKUP:
        cert_data = CERT_LOOKUP[normalized_name]
        if cert_data['expiry_date'] is not None:
            return (
                evaluate_date_status(cert_data['expiry_date']),
                cert_data['expiry_raw'],
                cert_data['expiry_date'],
                f"cert-data.csv: {cert_data['original_name']}"
            )
    
    # Partial match - check if any cert product name is contained in the search name
    for cert_name, cert_data in CERT_LOOKUP.items():
        if cert_name in normalized_name or normalized_name in cert_name:
            if cert_data['expiry_date'] is not None:
                return (
                    evaluate_date_status(cert_data['expiry_date']),
                    cert_data['expiry_raw'],
                    cert_data['expiry_date'],
                    f"cert-data.csv (partial match): {cert_data['original_name']}"
                )
    
    return None


# -------------
# API ACCESS (keeping existing functions)
# -------------

_session = requests.Session()
API_AVAILABLE = True
_consecutive_failures = 0


def api_get(url):
    global API_AVAILABLE, _consecutive_failures
    if not API_AVAILABLE:
        return None
    try:
        r = _session.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            _consecutive_failures = 0
            return r.json()
        if r.status_code == 404:
            _consecutive_failures = 0
            return None
        raise requests.HTTPError(f"HTTP {r.status_code}")
    except Exception as exc:
        _consecutive_failures += 1
        print(f"[WARN] API request failed ({url}): {exc}")
        if _consecutive_failures >= MAX_CONSECUTIVE_API_FAILURES:
            API_AVAILABLE = False
            print("[WARN] Too many API failures - skipping further lookups.")
        return None


def tokenize(text):
    text = re.sub(r'\([^)]*\)', ' ', str(text).lower())
    return tuple(re.findall(r'[a-z0-9]+', text))


PRODUCT_INDEX = {}
PRODUCT_SLUGS = set()


def load_product_index():
    global PRODUCT_INDEX, PRODUCT_SLUGS
    data = api_get(EOL_PRODUCTS_URL)
    if data is None:
        return
    products = data.get('result', data.get('products', data.get('data', []))) if isinstance(data, dict) else data

    index = {}
    slugs = set()
    secondary = []
    for p in products or []:
        if isinstance(p, str):
            slug, extras = p, []
        elif isinstance(p, dict):
            slug = p.get('name') or p.get('id') or p.get('slug')
            extras = [p.get('label')] + list(p.get('aliases') or [])
        else:
            continue
        if not slug:
            continue
        slugs.add(slug)
        toks = tokenize(slug)
        if toks:
            index.setdefault(toks, slug)
        secondary.extend((tokenize(e), slug) for e in extras if e)

    for toks, slug in secondary:
        if toks:
            index.setdefault(toks, slug)
    PRODUCT_INDEX = index
    PRODUCT_SLUGS = slugs

    for _, slug in ALIASES:
        if slug not in slugs:
            print(f"[WARN] ALIASES entry points at unknown endoflife.date slug: {slug!r}")


_PRODUCT_NAME_CACHE = {}


def _first_content_index(tokens):
    for i, t in enumerate(tokens):
        if t not in VENDOR_WORDS:
            return i
    return 0


def find_product_slug(name):
    if is_blank(name) or not PRODUCT_INDEX:
        return None
    if name in _PRODUCT_NAME_CACHE:
        return _PRODUCT_NAME_CACHE[name]

    lowered = str(name).lower()
    slug = None
    for pattern, alias_slug in ALIASES:
        if alias_slug in PRODUCT_SLUGS and re.search(pattern, lowered):
            slug = alias_slug
            break

    if slug is None:
        tokens = tokenize(name)
        slug = PRODUCT_INDEX.get(tokens)
        if slug is None and tokens:
            start = _first_content_index(tokens)
            best = None
            for i in sorted({0, start}):
                for j in range(len(tokens), i, -1):
                    sub = tokens[i:j]
                    cand = PRODUCT_INDEX.get(sub)
                    if not cand or cand in NO_PARTIAL_SLUGS:
                        continue
                    chars = len(''.join(sub))
                    if chars < MIN_PARTIAL_MATCH_CHARS:
                        continue
                    score = (len(sub), chars)
                    if best is None or score > best[0]:
                        best = (score, cand)
            slug = best[1] if best else None

    _PRODUCT_NAME_CACHE[name] = slug
    return slug


_RELEASE_CACHE = {}


def get_releases(slug):
    if slug in _RELEASE_CACHE:
        return _RELEASE_CACHE[slug]
    data = api_get(f'{EOL_API_BASE}{slug}')
    releases = []
    if isinstance(data, dict):
        payload = data.get('result', data)
        if isinstance(payload, dict):
            releases = payload.get('releases', [])
    elif isinstance(data, list):
        releases = data
    _RELEASE_CACHE[slug] = releases or []
    return _RELEASE_CACHE[slug]


def _version_tokens(text):
    return [str(int(t)) if t.isdigit() else t for t in re.findall(r'[a-z0-9]+', str(text).lower())]


def match_release(releases, version):
    v = _version_tokens(version)
    best, best_len = None, 0
    for rel in releases:
        if not isinstance(rel, dict):
            continue
        cycle = _version_tokens(rel.get('name', rel.get('cycle', '')))
        if cycle and v[:len(cycle)] == cycle and len(cycle) > best_len:
            best, best_len = rel, len(cycle)
    return best


def version_candidates(name, version):
    cands = []
    if not is_blank(version) and str(version).strip().lower() != '(unknown)':
        cands.append(str(version).strip())
    for m in re.findall(r'\d+(?:\.\d+)+', str(name)):
        if m not in cands:
            cands.append(m)
    return cands


def lookup_eol(name, version):
    if not PRODUCT_INDEX:
        return None, 'API_UNAVAILABLE'
    cands = version_candidates(name, version)
    if not cands:
        return None, 'NO_VERSION'
    slug = find_product_slug(name)
    if not slug:
        return None, 'NOT_ON_ENDOFLIFE_DATE'
    releases = get_releases(slug)
    if not releases:
        return None, f'NO_RELEASE_DATA ({slug})'

    rel = None
    for v in cands:
        rel = match_release(releases, v)
        if rel is not None:
            break
    if rel is None:
        return None, f'NO_MATCHING_RELEASE ({slug}, version {cands[0]})'

    cycle = rel.get('name', rel.get('cycle', '?'))
    source = f'endoflife.date:{slug} cycle {cycle}'
    eol = rel.get('eolFrom', rel.get('eol'))
    dt = parse_date(eol) if isinstance(eol, str) else None
    if dt is not None:
        return (evaluate_date_status(dt), dt.strftime('%Y-%m-%d'), dt, source), ''
    if eol is True or rel.get('isEol') is True:
        return (TAG_EXPIRED, 'Expired (no date given)', None, source), ''
    if eol is False or rel.get('isEol') is False:
        return (TAG_OK, 'No EOL announced', None, source), ''
    return None, f'NO_EOL_INFO ({slug} cycle {cycle})'


# -----------------------------
# Main CSV Processing Routine
# -----------------------------

def repair_row(fields, n):
    if len(fields) <= n:
        return fields
    out = []
    surplus = len(fields) - n
    for i, f in enumerate(fields):
        if i > 0 and surplus > 0 and f[:1] == ' ':
            out[-1] = out[-1] + ',' + f
            surplus -= 1
        else:
            out.append(f)
    return out if len(out) == n else None


def read_csv_safely(filepath):
    for enc in ('utf-8-sig', 'cp1252'):
        try:
            with open(filepath, newline='', encoding=enc) as fh:
                rows = list(csv.reader(fh))
        except UnicodeDecodeError:
            continue
        if not rows:
            return pd.DataFrame()
        header = [str(c).strip() for c in rows[0]]
        n = len(header)
        good, repaired, unfixable = [], 0, []
        for line_no, fields in enumerate(rows[1:], start=2):
            if not any(f.strip() for f in fields):
                continue
            if len(fields) == n:
                good.append(fields)
                continue
            fixed = repair_row(fields, n)
            if fixed is not None:
                good.append(fixed)
                repaired += 1
            elif len(fields) < n:
                good.append(fields + [''] * (n - len(fields)))
            else:
                unfixable.append(line_no)
        if repaired:
            print(f"[INFO] {os.path.basename(filepath)}: repaired {repaired} rows with unquoted commas")
        if unfixable:
            print(f"[WARN] {os.path.basename(filepath)}: {len(unfixable)} rows could not be repaired")
        return pd.DataFrame(good, columns=header, dtype=str)
    raise ValueError(f"Could not decode {filepath}")


def pick_columns(cols):
    columns = {'name_col': None, 'version_col': None, 'eol_col': None, 'note_col': None}
    for name_col, version_col in SOFTWARE_COL_OPTIONS:
        if name_col in cols:
            columns['name_col'] = name_col
            columns['version_col'] = version_col if version_col in cols else None
            break
    for col in EOL_COL_OPTIONS:
        if col in cols:
            columns['eol_col'] = col
            break
    for col in NOTE_COL_OPTIONS:
        if col in cols:
            columns['note_col'] = col
            break
    return columns


def tag_row(row, columns, use_api):
    """Returns (tag, eol_display, eol_timestamp, source, note)."""
    eol_col = columns['eol_col']
    raw = row.get(eol_col) if eol_col else None
    file_note = row.get(columns['note_col']) if columns['note_col'] else None
    file_note = '' if is_blank(file_note) else str(file_note).strip()

    # 1) Use the file's own date if it has a real one
    dt = parse_date(raw)
    if dt is not None:
        return evaluate_date_status(dt), raw, dt, 'file', file_note

    # 2) Check EOS report
    name = row.get(columns['name_col'])
    version = row.get(columns['version_col']) if columns['version_col'] else None
    
    eos_result = lookup_eos_report(name, version)
    if eos_result:
        tag, display, ts, source = eos_result
        return tag, display, ts, source, file_note

    # 3) Check certification data
    cert_result = lookup_cert_expiry(name, version)
    if cert_result:
        tag, display, ts, source = cert_result
        return tag, display, ts, source, file_note

    # 4) Otherwise ask endoflife.date (not for cert files)
    reason = ''
    if use_api:
        found, reason = lookup_eol(name, version)
        if found:
            tag, display, ts, source = found
            return tag, display, ts, source, file_note
    else:
        cert_date = row.get('Date Certified')
        reason = 'CERT_EXPIRY_BLANK' + ('' if is_blank(cert_date) else f' (certified {cert_date})')

    # 5) Nothing usable
    raw_txt = '' if raw is None or (isinstance(raw, float) and pd.isna(raw)) else str(raw).strip()
    parts = [reason or 'NO_DATA']
    if raw_txt:
        parts.append(f'file says "{raw_txt}"')
    if file_note:
        parts.append(file_note)
    return TAG_REVIEW, None, None, '', ' | '.join(parts)


def sort_sections(df):
    df['_group'] = df['EOL_Tag'].map(TAG_SORT_ORDER)
    df['_name_key'] = df['Name'].fillna('').astype(str).str.lower()
    df['_eol_dt'] = pd.to_datetime(df['_eol_dt'], errors='coerce')
    df = df.sort_values(['_group', '_eol_dt', '_name_key'], na_position='last', kind='stable')
    df = df[OUTPUT_COLS]

    if not ADD_SECTION_HEADERS:
        return df

    parts = []
    for title, tags in SECTION_HEADERS:
        section = df[df['EOL_Tag'].isin(tags)]
        if section.empty:
            continue
        blank = {c: '' for c in OUTPUT_COLS}
        blank['EOL_Tag'] = title
        header = pd.DataFrame([blank], columns=OUTPUT_COLS)
        parts.extend([header, section])
    return pd.concat(parts, ignore_index=True) if parts else df


def process_csv(filepath):
    df = read_csv_safely(filepath)
    fname = os.path.basename(filepath)
    columns = pick_columns(list(df.columns))
    if not columns['name_col']:
        return None

    is_cert = 'cert' in fname.lower() or columns['eol_col'] == 'Certification Expiry'
    use_api = not is_cert

    rows = []
    for _, row in df.iterrows():
        tag, eol_display, eol_dt, source, note = tag_row(row, columns, use_api)
        name = row.get(columns['name_col'])
        version = row.get(columns['version_col']) if columns['version_col'] else None
        rows.append({
            'EOL_Tag': tag,
            'Name': name.strip() if isinstance(name, str) else name,
            'Version': version.strip() if isinstance(version, str) else version,
            'EOL Date': eol_display,
            'Source': source,
            'Note': note,
            '_eol_dt': eol_dt,
        })

    out = pd.DataFrame(rows, columns=BASE_COLS + ['Source', 'Note', '_eol_dt'])
    return sort_sections(out)


def print_review_breakdown(result, fname):
    if 'Note' not in result.columns:
        return
    rev = result[result['EOL_Tag'] == TAG_REVIEW]
    if rev.empty:
        return
    kinds = rev['Note'].fillna('').str.extract(r'((?:[A-Z_]{4,}))', expand=False).fillna('OTHER')
    print(f"        review reasons for {fname}: " +
          ", ".join(f"{k}={v}" for k, v in kinds.value_counts().items()))


def main():
    if not DATA_DIR.exists():
        print(f"[ERROR] Data folder not found: {DATA_DIR}")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Load EOS report first (adaptive to month in filename)
    load_eos_report()
    
    # Load certification data
    load_cert_data()
    
    # Load API product index
    load_product_index()
    if PRODUCT_INDEX:
        print(f"[INFO] Loaded {len(PRODUCT_INDEX)} product names from endoflife.date")
    else:
        print("[WARN] Could not load the endoflife.date product list; API lookups disabled.")

    for path in sorted(DATA_DIR.glob('*.csv')):
        if path.stem.endswith(PARSED_SUFFIX) or path.name == CERT_DATA_FILE:
            continue
        result = process_csv(path)
        if result is None:
            print(f"[SKIP] {path.name}: no recognized name column")
            continue

        out_file = OUTPUT_DIR / f"{path.stem}{PARSED_SUFFIX}.csv"
        result.to_csv(out_file, index=False, encoding='utf-8-sig')
        counts = result['EOL_Tag'].value_counts()
        print(f"[SUCCESS] {path.name} -> {out_file.name}  "
              f"(expired: {counts.get(TAG_EXPIRED, 0)}, review: {counts.get(TAG_REVIEW, 0)}, "
              f"expiring soon: {counts.get(TAG_WARN, 0)}, ok: {counts.get(TAG_OK, 0)})")
        print_review_breakdown(result, path.name)


if __name__ == "__main__":
    main()