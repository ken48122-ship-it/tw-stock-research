create or replace function public.ingest_twse_prices_v1(p_rows jsonb)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare r jsonb; sid bigint; n integer := 0; changed integer := 0; affected integer; run_id bigint;
begin
 if jsonb_typeof(p_rows) <> 'array' or jsonb_array_length(p_rows) not between 1 and 5000 then raise exception 'Invalid batch'; end if;
 perform pg_advisory_xact_lock(481221);
 insert into public.pipeline_runs(pipeline_name,status,rows_read) values ('twse_daily_prices_v1','running',jsonb_array_length(p_rows)) returning id into run_id;
 for r in select value from jsonb_array_elements(p_rows) loop
  if coalesce(r->>'stock_id','') !~ '^[0-9A-Za-z]{4,6}$' or coalesce(r->>'revision','') !~ '^[a-f0-9]{64}$'
    or r->>'name' is null or r->>'trade_date' is null or r->'raw' is null then raise exception 'Invalid row'; end if;
  if (r->>'trade_date')::date > (now() at time zone 'Asia/Taipei')::date
    or (r->>'volume_shares')::numeric < 0 or (r->>'turnover_twd')::numeric < 0
    or (r->>'high_price')::numeric < (r->>'low_price')::numeric then raise exception 'Invalid date or price'; end if;
  insert into public.companies(stock_id,name,market,industry)
   values(r->>'stock_id',r->>'name','TWSE',r->>'industry')
   on conflict(stock_id) do update set name=excluded.name,industry=excluded.industry,updated_at=now()
   where companies.market='TWSE';
  insert into public.source_records(source_name,dataset,stock_id,period_end,source_url,source_record_key,revision,raw)
   values('TWSE','STOCK_DAY_ALL',r->>'stock_id',(r->>'trade_date')::date,
    'https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL',
    (r->>'stock_id')||':'||(r->>'trade_date'),r->>'revision',r->'raw')
   on conflict(source_name,dataset,source_record_key,revision) do nothing returning id into sid;
  if sid is null then
   select id into sid from public.source_records where source_name='TWSE' and dataset='STOCK_DAY_ALL'
    and source_record_key=(r->>'stock_id')||':'||(r->>'trade_date') and revision=r->>'revision';
  end if;
  insert into public.daily_prices(stock_id,trade_date,open_price,high_price,low_price,close_price,volume_shares,turnover_twd,source_record_id)
   values(r->>'stock_id',(r->>'trade_date')::date,(r->>'open_price')::numeric,(r->>'high_price')::numeric,
    (r->>'low_price')::numeric,(r->>'close_price')::numeric,(r->>'volume_shares')::numeric,(r->>'turnover_twd')::numeric,sid)
   on conflict(stock_id,trade_date) do update set open_price=excluded.open_price,high_price=excluded.high_price,
    low_price=excluded.low_price,close_price=excluded.close_price,volume_shares=excluded.volume_shares,
    turnover_twd=excluded.turnover_twd,source_record_id=excluded.source_record_id
   where daily_prices.source_record_id is distinct from excluded.source_record_id;
  get diagnostics affected = row_count;
  changed := changed + affected; n := n + 1;
 end loop;
 update public.pipeline_runs set status='success',finished_at=now(),rows_written=changed,
 details=jsonb_build_object('scope','TWSE listed companies','processed',n) where id=run_id;
 return jsonb_build_object('processed',n,'changed',changed,'run_id',run_id);
end $$;
revoke all on function public.ingest_twse_prices_v1(jsonb) from public,anon,authenticated;
grant execute on function public.ingest_twse_prices_v1(jsonb) to service_role;
grant select,insert,update on public.companies,public.source_records,public.daily_prices,public.pipeline_runs to service_role;
grant usage,select on all sequences in schema public to service_role;
