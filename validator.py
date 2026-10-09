"""TWSE listed-company price validation. Python standard library only."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request
import urllib.error
from decimal import Decimal, InvalidOperation

PRICES = 'https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL'
COMPANIES = 'https://openapi.twse.com.tw/v1/opendata/t187ap03_L'
TAIPEI = dt.timezone(dt.timedelta(hours=8))

def fetch(url, body=None, headers=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body, ensure_ascii=False).encode(), headers={'User-Agent': 'tw-stock-research/0.1', 'Content-Type': 'application/json', **(headers or {})})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                if '/rest/v1/rpc/' in url:
                    try:
                        error = json.loads(exc.read())
                        message = str(error.get('message', ''))[:500]
                        for secret in (headers or {}).values():
                            message = message.replace(secret, '[redacted]')
                        raise RuntimeError(f"Database HTTP {exc.code}: {error.get('code', 'unknown')} {message}") from None
                    except (ValueError, UnicodeError):
                        pass
                raise RuntimeError(f'HTTP {exc.code}; response omitted to protect credentials') from None
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise RuntimeError('Network request failed after 3 attempts') from None
        time.sleep(2 ** attempt)

def parse_date(value):
    s = str(value).replace('/', '').replace('-', '')
    if len(s) == 7:
        s = str(int(s[:3]) + 1911) + s[3:]
    if len(s) != 8 or not s.isdigit():
        raise ValueError('invalid date')
    return dt.datetime.strptime(s, '%Y%m%d').date()

def number(value, optional=False):
    if value in ('', '--', '---', None):
        if optional:
            return None
        raise ValueError('missing required number')
    try:
        n = Decimal(str(value).replace(',', ''))
    except InvalidOperation:
        raise ValueError('invalid number') from None
    if not n.is_finite() or n < 0:
        raise ValueError('negative or nonfinite number')
    return str(n)

def validate(companies, prices, today=None):
    today = today or dt.datetime.now(TAIPEI).date()
    if not isinstance(companies, list) or not companies or not isinstance(prices, list) or not prices:
        raise ValueError('empty or malformed source')
    master = {}
    for c in companies:
        code = c['公司代號'].strip()
        if code in master:
            raise ValueError('duplicate company')
        master[code] = c
    rows, seen, dates = [], set(), set()
    for raw in prices:
        code = raw['Code'].strip()
        if code not in master:
            continue
        day = parse_date(raw['Date'])
        if day > today or (today - day).days > 14:
            raise ValueError('future or stale source date')
        key = (code, day)
        if key in seen:
            raise ValueError('duplicate company/date')
        seen.add(key)
        dates.add(day)
        values = [number(raw[k], optional=True) for k in ('OpeningPrice', 'HighestPrice', 'LowestPrice', 'ClosingPrice')]
        o, h, l, c = [Decimal(v) if v is not None else None for v in values]
        if any(v is not None and v <= 0 for v in (o, h, l, c)):
            raise ValueError('nonpositive price')
        if h is not None and l is not None and (h < l or any(v is not None and not l <= v <= h for v in (o, c))):
            raise ValueError('invalid OHLC range')
        volume, turnover = number(raw['TradeVolume'], optional=True), number(raw['TradeValue'], optional=True)
        if volume is not None and Decimal(volume) != Decimal(volume).to_integral_value():
            raise ValueError('fractional shares')
        company = master[code]
        row = dict(stock_id=code, name=company['公司簡稱'], industry=company['產業別'], trade_date=day.isoformat(), open_price=values[0], high_price=values[1], low_price=values[2], close_price=values[3], volume_shares=volume, turnover_twd=turnover, raw=raw)
        row['revision'] = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        rows.append(row)
    if not rows or len(dates) != 1:
        raise ValueError('no matched prices or mixed dates')
    if len(rows) / len(master) < 0.90:
        raise ValueError('company coverage below 90%')
    return rows

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--prices-file')
    p.add_argument('--companies-file')
    p.add_argument('--write', action='store_true')
    p.add_argument('--output', default='run-result.json')
    p.add_argument('--payload-output')
    args = p.parse_args()
    report = {'status': 'failed', 'scope': 'TWSE listed companies only'}
    try:
        read = lambda path, url: json.loads(Path(path).read_text(encoding='utf-8-sig')) if path else fetch(url)
        rows = validate(read(args.companies_file, COMPANIES), read(args.prices_file, PRICES))
        payload = {'p_rows': rows}
        if args.payload_output:
            Path(args.payload_output).write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        report.update(status='validated', rows=len(rows), trade_date=rows[0]['trade_date'])
        if args.write:
            url = os.environ.get('SUPABASE_URL', '').rstrip('/')
            key = os.environ.get('SUPABASE_SECRET_KEY', '')
            if url != 'https://kgkjlrzvdfrpxujgivrt.supabase.co' or not key.startswith('sb_secret_'):
                raise ValueError('Set the expected SUPABASE_URL and backend SUPABASE_SECRET_KEY')
            report['database'] = fetch(url + '/rest/v1/rpc/ingest_twse_prices_v1', payload, {'apikey': key})
            report['status'] = 'written'
    except Exception as exc:
        report.update(status='failed', error=str(exc))
        raise
    finally:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))

if __name__ == '__main__':
    main()
