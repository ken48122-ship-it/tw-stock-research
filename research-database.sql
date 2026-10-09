create or replace function public.ingest_twse_research_v1(p_data jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare s jsonb; r jsonb; f record; sid bigint; rid bigint; vdate date; added integer:=0; fact_count integer:=0; n integer;
begin
 vdate := (p_data->'report'->>'as_of_date')::date;
 if vdate is distinct from (now() at time zone 'Asia/Taipei')::date or p_data->'report'->>'model_version' is distinct from 'research-v1.0'
 or jsonb_array_length(p_data->'sources') not between 1 and 10000
 or jsonb_array_length(p_data->'rankings') not between 1 and 60 then raise exception 'Invalid research batch'; end if;
 perform pg_advisory_xact_lock(481222);
 insert into public.pipeline_runs(pipeline_name,status,rows_read)
 values('twse_research_v1','running',jsonb_array_length(p_data->'sources')) returning id into rid;
 for s in select value from jsonb_array_elements(p_data->'sources') loop
  if s->>'dataset' not in ('income','balance','revenue','valuation') or s->>'revision' !~ '^[a-f0-9]{64}$' then raise exception 'Invalid source'; end if;
  if not exists(select 1 from public.companies where stock_id=s->>'stock_id') then
   raise exception 'Company missing from price ingestion: %',s->>'stock_id';
  end if;
  insert into public.source_records(source_name,dataset,stock_id,period_end,source_url,source_record_key,revision,raw)
   values('TWSE','research_'||(s->>'dataset'),s->>'stock_id',(s->>'period_end')::date,s->>'source_url',
   (s->>'stock_id')||':'||(s->>'period_end'),s->>'revision',s->'raw')
   on conflict(source_name,dataset,source_record_key,revision) do nothing returning id into sid;
  get diagnostics n = row_count; added:=added+n;
  if sid is null then
   select id into sid from public.source_records where source_name='TWSE' and dataset='research_'||(s->>'dataset')
    and source_record_key=(s->>'stock_id')||':'||(s->>'period_end') and revision=s->>'revision';
  end if;
  if s->>'dataset' in ('income','balance') then
   for f in select key,value from jsonb_each_text(s->'facts') loop
    insert into public.financial_facts(stock_id,period_end,statement_type,account_code,account_name,value,unit,statement_basis,source_record_id)
    values(s->>'stock_id',(s->>'period_end')::date,s->>'dataset',f.key,f.key,f.value::numeric,
     case when f.key='eps_ytd' then 'TWD/share' else 'source_report_unit' end,
     case when s->>'dataset'='income' then 'TWSE_CI_YTD' else 'TWSE_CI_POINT_IN_TIME' end,sid)
    on conflict(stock_id,period_end,statement_type,account_code,statement_basis,source_record_id) do nothing;
    get diagnostics n=row_count; fact_count:=fact_count+n;
   end loop;
  elsif s->>'dataset'='revenue' then
   insert into public.monthly_revenue(stock_id,revenue_month,revenue_thousand_twd,source_record_id)
    values(s->>'stock_id',(s->>'period_end')::date,(s->'facts'->>'monthly_revenue')::numeric,sid)
    on conflict(stock_id,revenue_month) do update set revenue_thousand_twd=excluded.revenue_thousand_twd,source_record_id=excluded.source_record_id;
  end if;
 end loop;
 for r in select value from jsonb_array_elements(p_data->'scores') loop
  for f in select key,value from jsonb_each_text(r->'factors') loop
   insert into public.factor_values(stock_id,as_of_date,factor_code,value,unit,available_at,data_status,calculation_version)
    values(r->>'stock_id',vdate,f.key,f.value::numeric,case when f.key in ('pe','pb') then 'ratio' else 'percent_or_pp' end,
     now(),case when f.value is null then 'missing' else 'valid' end,'research-v1.0')
    on conflict(stock_id,as_of_date,factor_code,calculation_version) do update
     set value=excluded.value,available_at=excluded.available_at,data_status=excluded.data_status;
  end loop;
  insert into public.factor_scores(stock_id,as_of_date,model_version,growth_score,quality_score,valuation_score,total_score,coverage_ratio,eligibility_status)
   values(r->>'stock_id',vdate,'research-v1.0',(r->>'growth_score')::numeric,(r->>'quality_score')::numeric,
    (r->>'valuation_score')::numeric,(r->>'total_score')::numeric,(r->>'coverage_ratio')::numeric,
    case when r->>'total_score' is null then 'excluded' else 'eligible_unbacktested' end)
   on conflict(stock_id,as_of_date,model_version) do update
   set growth_score=excluded.growth_score,quality_score=excluded.quality_score,valuation_score=excluded.valuation_score,
    total_score=excluded.total_score,coverage_ratio=excluded.coverage_ratio,eligibility_status=excluded.eligibility_status;
 end loop;
 delete from public.ranking_snapshots where as_of_date=vdate and model_version='research-v1.0';
 for r in select value from jsonb_array_elements(p_data->'rankings') loop
  if (r->>'score')::numeric not between 0 and 100 then raise exception 'Invalid score'; end if;
  insert into public.ranking_snapshots(ranking_type,as_of_date,rank,stock_id,score,model_version,rationale)
   values(r->>'ranking_type',vdate,(r->>'rank')::integer,r->>'stock_id',(r->>'score')::numeric,'research-v1.0',r->'rationale');
 end loop;
 update public.pipeline_runs set status='success',finished_at=now(),rows_written=added,
 details=jsonb_build_object('report',p_data->'report','new_financial_facts',fact_count,'ranking_rows',jsonb_array_length(p_data->'rankings'))
 where id=rid;
 return jsonb_build_object('run_id',rid,'new_sources',added,'new_financial_facts',fact_count,'rankings',jsonb_array_length(p_data->'rankings'));
end $$;
revoke all on function public.ingest_twse_research_v1(jsonb) from public,anon,authenticated;
grant execute on function public.ingest_twse_research_v1(jsonb) to service_role;
grant select,insert,update on public.financial_facts,public.monthly_revenue,public.factor_values,public.factor_scores to service_role;
grant select,insert,update,delete on public.ranking_snapshots to service_role;

create or replace function public.save_research_summary_v1(p_run_id bigint,p_summary jsonb)
returns boolean language plpgsql security invoker set search_path='' as $$
begin
 if length(p_summary::text)>30000 or p_summary->>'status' not in ('ai_generated','deterministic_fallback') then raise exception 'Invalid summary'; end if;
 update public.pipeline_runs set details=details||jsonb_build_object('summary',p_summary)
 where id=p_run_id and pipeline_name='twse_research_v1' and status='success';
 return found;
end $$;
revoke all on function public.save_research_summary_v1(bigint,jsonb) from public,anon,authenticated;
grant execute on function public.save_research_summary_v1(bigint,jsonb) to service_role;
