# 台股研究自動化

Python 驗證證交所上市行情，以 Supabase 原子函式入庫。尚未涵蓋上櫃、財報與 AI 評分。

## 執行

Python 3.12，無第三方套件。

```sh
python -m unittest discover -s tests -v
python validator.py
python validator.py --write
```

寫入需要環境變數 SUPABASE_URL 與 SUPABASE_SECRET_KEY（sb_secret_ 開頭），不要提交密鑰。

## 自動排程

.github/workflows/daily.yml 設定平日台北 18:37 執行。請先在 GitHub Actions Secrets 設定 SUPABASE_SECRET_KEY，再手動執行 workflow 驗證。程式部署不代表密鑰已設定或資料庫寫入成功。

既有 Supabase 專案已部署 database.sql，無需重建。資料來源保留原始行情與內容雜湊；重跑不重複入庫。缺值保留 NULL，資料日期不以執行日代替。

最新公司名單及最新修訂行情不適合直接作無前瞻偏誤回測。14 日新鮮度限制不是交易日曆。
