# 台股研究自動化

每週一至週五台北時間 18:37 啟動 GitHub Actions（平台可能延遲），亦可手動執行。資料寫入 Supabase，報告保留為 Actions 摘要及 14 天下載附件。

流程：官方上市名單與收盤價驗證 → 一般產業損益與資產負債表、月營收、估值 → 三種各 20 名研究排行榜 → 本機 AI 摘要。

- validator.py：上市公司與日行情，保留官方來源、交易日、雜湊與執行紀錄。
- research.py：財報與可解釋評分；缺值、期間不一致、不符資格者排除。
- ai_summary.py：Qwen2.5 1.5B 只挑選已驗證的重點，不能新增財務敘述或數字。AI 失敗明確標記規則備援摘要。
- setup_ai.py：在暫時的 GitHub runner 執行固定版本 Ollama，驗證下載雜湊；不需要付費 AI API 金鑰。
- METHODOLOGY.md：評分公式、資料日期與限制。

僅供研究；尚未回測。未包含金融業專用財報、現金流、ROIC、法人與價格動能。營收加速榜是轉折代理，不代表已驗證的獲利轉折。

GitHub Secret SUPABASE_SECRET_KEY 僅在排程或手動執行注入。請勿將後端金鑰放入程式、報告或前端。資料庫使用 RLS，寫入 RPC 僅授權 service_role。

本機驗證：python -m unittest discover -s tests -v。手動執行可在 Actions 選擇 Taiwan stock daily research → Run workflow。
