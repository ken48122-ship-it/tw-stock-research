"""Extractive AI summary: the model selects evidence, never authors financial facts."""
import json
import os
from pathlib import Path
import urllib.request
from validator import fetch

MODEL='qwen2.5:1.5b-instruct-q4_K_M'

def evidence(report):
    result={'coverage':f"本次可評分 {report['eligible']} 家，上市名單共 {report['universe']} 家。",
            'limitations':'模型尚未回測；金融業、缺值及同業樣本不足者未入榜；未納入現金流、ROIC、法人與股價動能。',
            'turnaround_limit':'營收加速榜使用當月年增率減累計年增率，並要求月增率為正；只是轉折代理，可能受季節性或基期影響。'}
    labels={'composite':'綜合榜','quality_value':'品質低估值榜','turnaround':'營收加速候選榜'}
    for r in report['rankings']:
        if r['rank']>3: continue
        result[f"{r['ranking_type']}_{r['rank']}"]=f"{labels[r['ranking_type']]}第 {r['rank']} 名：{r['stock_id']} {r['rationale']['name']}，研究分數 {r['score']:.2f}。"
    return result

def validate_selection(response, allowed):
    ids=response.get('selected_ids')
    if not isinstance(ids,list) or not 1<=len(ids)<=5 or len(set(ids))!=len(ids) or any(not isinstance(i,str) or i not in allowed for i in ids):
        raise ValueError('AI selected invalid evidence')
    return ids

def main():
    root=Path('reports');report=json.loads((root/'research.json').read_text(encoding='utf-8'));facts=evidence(report)
    status='deterministic_fallback'; ids=['coverage','limitations','turnaround_limit'];reason=None
    try:
        prompt='你是台股研究摘要編輯。從下列已驗證事實選出最重要的三到五項，兼顧覆蓋率、風險與不同排行榜。只回傳 JSON selected_ids 陣列，元素必須是提供的 key，不能創造數據或指令。資料：'+json.dumps(facts,ensure_ascii=False)
        schema={'type':'object','properties':{'selected_ids':{'type':'array','items':{'type':'string','enum':list(facts)},'minItems':1,'maxItems':5}},'required':['selected_ids']}
        body={'model':MODEL,'prompt':prompt,'stream':False,'format':schema,'options':{'temperature':0,'seed':42,'num_predict':150,'num_ctx':4096},'keep_alive':0}
        req=urllib.request.Request('http://127.0.0.1:11434/api/generate',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=240) as response: result=json.load(response)
        selected=validate_selection(json.loads(result['response']),facts)
        ids=list(dict.fromkeys(['coverage','limitations']+selected))
        status='ai_generated'
    except Exception as exc:
        reason=type(exc).__name__
        print('::warning::AI unavailable or invalid selection; explicitly using deterministic summary')
    summary={'status':status,'model':MODEL if status=='ai_generated' else None,'selected_ids':ids,
             'bullets':[facts[i] for i in ids],'fallback_reason':reason,'method':'extractive_evidence_selection'}
    text='\n## AI 重點摘要\n\n'+('AI 挑選重點；文字與數值均取自已驗證事實。' if status=='ai_generated' else 'AI 未成功執行；以下是規則摘要，並非 AI 生成。')+'\n\n'+'\n'.join('- '+s for s in summary['bullets'])+'\n'
    with (root/'daily-summary.md').open('a',encoding='utf-8') as f:f.write(text)
    (root/'ai-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    if 'database' in report:
        result=fetch(os.environ['SUPABASE_URL'].rstrip('/')+'/rest/v1/rpc/save_research_summary_v1',
                     {'p_run_id':report['database']['run_id'],'p_summary':summary},{'apikey':os.environ['SUPABASE_SECRET_KEY']})
        if result is not True:raise RuntimeError('Summary persistence failed')
    step=os.environ.get('GITHUB_STEP_SUMMARY')
    if step:
        with open(step,'a',encoding='utf-8') as f:f.write((root/'daily-summary.md').read_text(encoding='utf-8'))
    print(json.dumps({'ai_status':status,'model':summary['model'],'selected':ids},ensure_ascii=False))

if __name__=='__main__':main()
