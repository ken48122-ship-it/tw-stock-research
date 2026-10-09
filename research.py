"""Versioned TWSE financial research; deterministic scores, evidence-only AI summary."""
import argparse
import calendar
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import time
from validator import fetch, parse_date, TAIPEI, COMPANIES

VERSION = 'research-v1.0'
BASE = 'https://openapi.twse.com.tw/v1'
ENDPOINTS = {
    'income': '/opendata/t187ap06_L_ci',
    'balance': '/opendata/t187ap07_L_ci',
    'revenue': '/opendata/t187ap05_L',
    'valuation': '/exchangeReport/BWIBBU_ALL',
}
FIELDS = {
    'income': {'revenue_ytd': '營業收入', 'gross_profit_ytd': '營業毛利（毛損）',
               'operating_profit_ytd': '營業利益（損失）', 'net_profit_ytd': '本期淨利（淨損）', 'eps_ytd': '基本每股盈餘（元）'},
    'balance': {'assets': '資產總計', 'liabilities': '負債總計', 'equity': '權益總計'},
}

def num(value):
    if value is None or str(value).strip() in ('', '--', '-', 'N/A'):
        return None
    s = str(value).strip().replace(',', '').replace('−', '-')
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]
    try:
        n = Decimal(s)
    except InvalidOperation:
        raise ValueError('Invalid financial number') from None
    if not n.is_finite():
        raise ValueError('Nonfinite financial number')
    return float(n)

def pct(a, b):
    return None if a is None or b is None or b <= 0 else 100 * a / b

def change(a, b):
    return None if a is None or b is None or b <= 0 else 100 * (a / b - 1)

def quarter(row):
    y, q = int(row['年度']), int(row['季別'])
    if y < 1911: y += 1911
    if q not in (1, 2, 3, 4): raise ValueError('Invalid quarter')
    return dt.date(y, q * 3, calendar.monthrange(y, q * 3)[1])

def revenue_month(value):
    s = str(value).replace('/', '').replace('-', '')
    if len(s) == 5: s = str(int(s[:3]) + 1911) + s[3:]
    if len(s) != 6: raise ValueError('Invalid revenue month')
    return dt.date(int(s[:4]), int(s[4:]), 1)

def source(kind, code, day, raw, facts):
    # Publication date is unknown. 出表日期 is an export date, never the historical availability date.
    content = {k: v for k, v in raw.items() if k != '出表日期'}
    revision = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return dict(dataset=kind, stock_id=code, period_end=day.isoformat(), source_url=BASE + ENDPOINTS[kind],
                revision=revision, raw=raw, facts=facts)

def normalize(data, companies, today):
    master = {r['公司代號']: r for r in companies}
    sources, maps, profile = [], {}, {}
    for kind, rows in data.items():
        if not isinstance(rows, list) or not rows: raise ValueError(f'Empty source: {kind}')
        indexed, dates, unlisted = {}, Counter(), 0
        for raw in rows:
            code = raw['Code'] if kind == 'valuation' else raw['公司代號']
            if code not in master:
                unlisted += 1
                continue
            if code in indexed: raise ValueError(f'Duplicate {kind} company: {code}')
            if kind in FIELDS:
                day = quarter(raw)
                if not 0 <= (today - day).days <= 200: raise ValueError(f'Stale/future {kind} quarter')
                if parse_date(raw['出表日期']) > today: raise ValueError('Future source export')
                facts = {k: num(raw[field]) for k, field in FIELDS[kind].items()}
                if kind == 'balance' and all(facts[k] is not None for k in ('assets','liabilities','equity')):
                    if abs(facts['assets'] - facts['liabilities'] - facts['equity']) > max(5, abs(facts['assets']) * 0.00001):
                        raise ValueError(f'Balance does not reconcile: {code}')
            elif kind == 'revenue':
                day = revenue_month(raw['資料年月'])
                end = day.replace(day=calendar.monthrange(day.year, day.month)[1])
                if not 0 <= (today - end).days <= 75: raise ValueError('Stale/future revenue month')
                current = num(raw['營業收入-當月營收'])
                if current is not None and current < 0: raise ValueError('Negative revenue')
                facts = {'monthly_revenue': current,
                         'revenue_yoy': change(current, num(raw['營業收入-去年當月營收'])),
                         'revenue_mom': change(current, num(raw['營業收入-上月營收'])),
                         'cumulative_yoy': change(num(raw['累計營業收入-當月累計營收']), num(raw['累計營業收入-去年累計營收']))}
            else:
                day = parse_date(raw['Date'])
                if not 0 <= (today - day).days <= 14: raise ValueError('Stale/future valuation date')
                facts = {k: num(raw[field]) for k, field in {'pe':'PEratio','pb':'PBratio','dividend_yield':'DividendYield'}.items()}
                for k in ('pe','pb'):
                    if facts[k] is not None and facts[k] <= 0: facts[k] = None
            indexed[code] = dict(period=day.isoformat(), **facts)
            dates[day.isoformat()] += 1
            sources.append(source(kind, code, day, raw, facts))
        if len(indexed) < len(master) * 0.8: raise ValueError(f'Insufficient source coverage: {kind}')
        maps[kind] = indexed
        profile[kind] = {'rows':len(indexed), 'periods':dict(dates), 'unlisted_excluded':unlisted}
    return sources, maps, master, profile

def percentile(values, value, higher=True):
    if len(values) < 5 or value is None: return None
    # Average tied rank mapped to [0,100]; all equal => 50.
    lower = sum(v < value for v in values)
    equal = sum(v == value for v in values)
    score = 100 * (lower + (equal - 1) / 2) / (len(values) - 1)
    return score if higher else 100 - score

def build_scores(maps, master, profile, today):
    common = {kind:max(p['periods'], key=p['periods'].get) for kind,p in profile.items()}
    rows = []
    for code, company in master.items():
        inc, bal, rev, val = [maps[k].get(code, {}) for k in ('income','balance','revenue','valuation')]
        f = {'revenue_yoy':rev.get('revenue_yoy'), 'revenue_mom':rev.get('revenue_mom'),
             'operating_margin':pct(inc.get('operating_profit_ytd'), inc.get('revenue_ytd')),
             'gross_margin':pct(inc.get('gross_profit_ytd'), inc.get('revenue_ytd')),
             'debt_ratio':pct(bal.get('liabilities'),bal.get('assets')), 'pe':val.get('pe'), 'pb':val.get('pb'),
             'acceleration':None if rev.get('revenue_yoy') is None or rev.get('cumulative_yoy') is None else rev['revenue_yoy']-rev['cumulative_yoy']}
        reasons=[]
        if not inc: reasons.append('financial_sector_or_missing_income')
        if any(maps[k].get(code,{}).get('period') != common[k] for k in common): reasons.append('missing_or_mixed_period')
        if inc.get('period') != bal.get('period'): reasons.append('income_balance_period_mismatch')
        if inc.get('eps_ytd') is None or inc.get('eps_ytd',0) <= 0: reasons.append('nonpositive_or_missing_eps')
        if f['operating_margin'] is None or f['operating_margin'] <= 0: reasons.append('nonpositive_or_missing_margin')
        rows.append({'stock_id':code,'name':company['公司簡稱'],'industry':company['產業別'],
                     'factors':f,'reasons':reasons,'periods':{k:maps[k].get(code,{}).get('period') for k in common}})
    groups=defaultdict(list)
    for r in rows:
        if not r['reasons']: groups[r['industry']].append(r)
    for r in rows:
        peers=groups[r['industry']]
        def rank(field, higher=True):
            return percentile([p['factors'][field] for p in peers if p['factors'][field] is not None],r['factors'][field],higher)
        r['growth_score']=rank('revenue_yoy')
        r['quality_score']=rank('operating_margin')
        r['valuation_score']=rank('pe',False)
        scores=[r[k] for k in ('growth_score','quality_score','valuation_score')]
        r['coverage_ratio']=sum(w for w,v in zip((.4,.4,.2),scores) if v is not None)
        if any(v is None for v in scores): r['reasons'].append('missing_factor_or_fewer_than_5_peers')
        r['total_score']=None if r['reasons'] else sum(w*v for w,v in zip((.4,.4,.2),scores))
        r['quality_value']=None if r['reasons'] else .5*r['quality_score']+.5*r['valuation_score']
        acceleration=rank('acceleration')
        r['turnaround']=None if r['reasons'] or acceleration is None or (r['factors']['acceleration'] or 0)<=0 or (r['factors']['revenue_mom'] or 0)<=0 else .6*acceleration+.4*r['quality_score']
    rankings=[]
    for kind,field in [('composite','total_score'),('quality_value','quality_value'),('turnaround','turnaround')]:
        candidates=sorted([r for r in rows if r[field] is not None],key=lambda r:(-r[field],r['stock_id']))[:20]
        for i,r in enumerate(candidates,1):
            rankings.append({'ranking_type':kind,'rank':i,'stock_id':r['stock_id'],'score':round(r[field],4),
                             'rationale':{'name':r['name'],'industry':r['industry'],'factors':r['factors'],'periods':r['periods'],
                                          'proxy':kind=='turnaround','model_version':VERSION}})
    return rows,rankings

def render(report):
    labels={'composite':'綜合榜','quality_value':'品質低估值榜','turnaround':'營收加速候選榜（轉折代理）'}
    lines=[f"# 台股研究摘要｜{report['as_of_date']}", '', f"模型：{VERSION}；範圍：上市一般產業，金融業與缺值公司排除。", '',
           '這是未經回測的研究排序，不是買賣建議。損益使用年初至季末累計數，並非單季。', '',
           '## 資料品質', '', f"評分 {report['eligible']} 家／上市名單 {report['universe']} 家；其餘未入榜。"]
    for kind,p in report['sources'].items(): lines.append(f"- {kind}：{p['rows']} 家；期間 {json.dumps(p['periods'],ensure_ascii=False)}")
    lines += ['', '未包含現金流、ROIC、法人籌碼、價格動能、五年回測；轉折榜僅為營收加速代理。',
              '歷史公告時間未驗證，以首次擷取時間表示資料可用時間，不把資料期末當公告日。', '']
    for kind,label in labels.items():
        lines += [f'## {label}', '', '|名次|代號|公司|分數|營收 YoY|營益率|P/E|', '|---:|---|---|---:|---:|---:|---:|']
        for r in report['rankings']:
            if r['ranking_type'] != kind: continue
            f=r['rationale']['factors']
            lines.append(f"|{r['rank']}|{r['stock_id']}|{r['rationale']['name'].replace('|','')}|{r['score']:.2f}|{f['revenue_yoy']:.2f}%|{f['operating_margin']:.2f}%|{f['pe']:.2f}|")
        if not any(r['ranking_type']==kind for r in report['rankings']): lines.append('沒有符合條件的公司。')
        lines.append('')
    lines += ['## 官方來源','']+[f'- [{k}]({BASE+v})' for k,v in ENDPOINTS.items()]
    return '\n'.join(lines)+'\n'

def main():
    p=argparse.ArgumentParser(); p.add_argument('--write',action='store_true'); p.add_argument('--fixtures'); args=p.parse_args()
    out=Path('reports');out.mkdir(exist_ok=True)
    today=dt.datetime.now(TAIPEI).date()
    data={}
    for kind,path in ENDPOINTS.items():
        data[kind]=json.loads((Path(args.fixtures)/(kind+'.json')).read_text()) if args.fixtures else fetch(BASE+path)
        if not args.fixtures: time.sleep(2)
    companies=fetch(COMPANIES) if not args.fixtures else json.loads((Path(args.fixtures)/'companies.json').read_text())
    sources,maps,master,profile=normalize(data,companies,today)
    rows,rankings=build_scores(maps,master,profile,today)
    report={'as_of_date':today.isoformat(),'model_version':VERSION,'sources':profile,'universe':len(master),
            'eligible':sum(r['total_score'] is not None for r in rows),'rankings':rankings,
            'excluded_reasons':dict(Counter(reason for r in rows for reason in r['reasons'])), 'ai_status':'pending'}
    if not rankings: raise ValueError('No eligible rankings; refusing empty publication')
    (out/'research.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'daily-summary.md').write_text(render(report),encoding='utf-8')
    if args.write:
        url=os.environ['SUPABASE_URL'].rstrip('/');key=os.environ['SUPABASE_SECRET_KEY']
        if url!='https://kgkjlrzvdfrpxujgivrt.supabase.co' or not key.startswith('sb_secret_'): raise ValueError('Invalid backend configuration')
        result=fetch(url+'/rest/v1/rpc/ingest_twse_research_v1',{'p_data':{'sources':sources,'scores':rows,'rankings':rankings,'report':report}}, {'apikey':key})
        report['database']=result
        (out/'research.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('as_of_date','universe','eligible','sources','excluded_reasons')},ensure_ascii=False))

if __name__=='__main__': main()
