import datetime as dt
import unittest
from validator import validate, number, parse_date

class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.companies = [{'公司代號': '2330', '公司簡稱': '台積電', '產業別': '24'}]
        self.row = dict(Date='1151008', Code='2330', OpeningPrice='10', HighestPrice='12', LowestPrice='9', ClosingPrice='11', TradeVolume='1,000', TradeValue='11000')
        self.today = dt.date(2026, 10, 9)
    def check(self, rows):
        return validate(self.companies, rows, self.today)
    def test_valid_roc_and_units(self):
        row = self.check([self.row])[0]
        self.assertEqual(row['trade_date'], '2026-10-08')
        self.assertEqual(row['volume_shares'], '1000')
    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError): self.check([self.row, self.row])
    def test_future_rejected(self):
        with self.assertRaises(ValueError): self.check([{**self.row, 'Date': '1151010'}])
    def test_range_rejected(self):
        with self.assertRaises(ValueError): self.check([{**self.row, 'ClosingPrice': '15'}])
    def test_null_preserved(self):
        self.assertIsNone(self.check([{**self.row, 'ClosingPrice': '--'}])[0]['close_price'])
    def test_missing_volume_not_zero(self):
        self.assertIsNone(self.check([{**self.row, 'TradeVolume': ''}])[0]['volume_shares'])
    def test_nonfinite_rejected(self):
        for value in ['NaN', 'Infinity', '-1']:
            with self.assertRaises(ValueError): number(value)
    def test_stale_rejected(self):
        with self.assertRaises(ValueError): self.check([{**self.row, 'Date': '1150901'}])
    def test_etf_excluded(self):
        self.assertEqual(len(self.check([self.row, {**self.row, 'Code': '0050'}])), 1)
    def test_empty_rejected(self):
        with self.assertRaises(ValueError): self.check([])
    def test_fractional_volume_rejected(self):
        with self.assertRaises(ValueError): self.check([{**self.row, 'TradeVolume': '1.5'}])

if __name__ == '__main__': unittest.main()
