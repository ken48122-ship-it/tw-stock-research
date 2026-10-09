import datetime as dt
import unittest
from research import num, change, percentile, quarter, revenue_month, build_scores, source, normalize
from ai_summary import validate_selection

class ResearchTests(unittest.TestCase):
    def test_negative_profit_and_missing(self):
        self.assertEqual(num('(1,234)'),-1234)
        self.assertIsNone(num(''))
        with self.assertRaises(ValueError): num('NaN')
    def test_growth_zero_base_unknown(self):
        self.assertIsNone(change(100,0))
        self.assertIsNone(change(100,-20))
        self.assertAlmostEqual(change(120,100),20)
    def test_period_not_export_date(self):
        self.assertEqual(quarter({'年度':'115','季別':'2'}),dt.date(2026,6,30))
        self.assertEqual(revenue_month('11508'),dt.date(2026,8,1))
    def test_ties_and_small_cohorts(self):
        self.assertEqual(percentile([2]*5,2),50)
        self.assertEqual(percentile([1,2,3,4,5],1,False),100)
        self.assertIsNone(percentile([1,2],1))
    def test_source_hash_ignores_export_day(self):
        a=source('income','2330',dt.date(2026,6,30),{'出表日期':'1151008','EPS':'1'}, {})
        b=source('income','2330',dt.date(2026,6,30),{'出表日期':'1151009','EPS':'1'}, {})
        self.assertEqual(a['revision'],b['revision'])
    def test_ai_cannot_invent_or_repeat_evidence(self):
        for ids in [['fake'],['a','a'],[]]:
            with self.assertRaises(ValueError): validate_selection({'selected_ids':ids},{'a':'fact'})
        self.assertEqual(validate_selection({'selected_ids':['a']},{'a':'fact'}),['a'])
    def test_negative_eps_and_missing_factor_excluded(self):
        masters={str(i):{'公司簡稱':str(i),'產業別':'24'} for i in range(8)}
        maps={k:{} for k in ('income','balance','revenue','valuation')}
        for i in masters:
            maps['income'][i]={'period':'2026-06-30','eps_ytd':1,'revenue_ytd':100,'operating_profit_ytd':20,'gross_profit_ytd':30}
            maps['balance'][i]={'period':'2026-06-30','assets':100,'liabilities':20}
            maps['revenue'][i]={'period':'2026-08-01','revenue_yoy':10,'revenue_mom':5,'cumulative_yoy':8}
            maps['valuation'][i]={'period':'2026-10-08','pe':10,'pb':2}
        maps['income']['0']['eps_ytd']=-1
        maps['valuation']['1']['pe']=None
        profile={k:{'periods':{next(iter(v.values()))['period']:8}} for k,v in maps.items()}
        rows,ranks=build_scores(maps,masters,profile,dt.date(2026,10,9))
        self.assertIsNone(rows[0]['total_score'])
        self.assertIsNone(rows[0]['growth_score'])
        self.assertIsNone(rows[1]['total_score'])
        self.assertEqual(rows[2]['total_score'],50)
        self.assertTrue(all(r['stock_id'] not in ('0','1') for r in ranks))
    def test_duplicate_source_rejected(self):
        raw={'Code':'2330','Date':'1151008','PEratio':'10','PBratio':'2','DividendYield':'3'}
        with self.assertRaises(ValueError): normalize({'valuation':[raw,raw]},[{'公司代號':'2330'}],dt.date(2026,10,9))
    def test_balance_reconciliation(self):
        raw={'公司代號':'2330','年度':'115','季別':'2','出表日期':'1151009','資產總計':'100','負債總計':'30','權益總計':'80'}
        with self.assertRaises(ValueError): normalize({'balance':[raw]},[{'公司代號':'2330'}],dt.date(2026,10,9))

if __name__=='__main__':unittest.main()
