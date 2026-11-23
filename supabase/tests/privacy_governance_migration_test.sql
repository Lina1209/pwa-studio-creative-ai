-- Transactional checks for privacy governance RPCs and immutable metadata journals.
begin;
do $$
declare
  v_user uuid := 'a31c7e5a-45a1-4bde-8b6c-8f7f95d7a901';
  v_other uuid := 'a31c7e5a-45a1-4bde-8b6c-8f7f95d7a902';
  v_request_key uuid := 'a31c7e5a-45a1-4bde-8b6c-8f7f95d7a903';
  v_request jsonb;
  v_request_2 jsonb;
  v_consent uuid;
  v_transfer uuid;
  v_correlation uuid := 'a31c7e5a-45a1-4bde-8b6c-8f7f95d7a904';
  v_race_correlation uuid := 'a31c7e5a-45a1-4bde-8b6c-8f7f95d7a905';
  v_action text;
  v_failed boolean := false;
begin
  insert into auth.users(id) values (v_user),(v_other) on conflict (id) do nothing;

  if not has_function_privilege('service_role',
       'public.record_privacy_consent_event(uuid,text,text,text,text,text,uuid)', 'EXECUTE')
     or has_function_privilege('authenticated',
       'public.record_privacy_consent_event(uuid,text,text,text,text,text,uuid)', 'EXECUTE')
     or has_function_privilege('anon',
       'public.record_privacy_consent_event(uuid,text,text,text,text,text,uuid)', 'EXECUTE') then
    raise exception 'consent RPC must be service-role-only';
  end if;

  v_consent := public.record_privacy_consent_event(
    v_user,'vision_deepseek','accepted','privacy-2026-01','vision-consent-2026-01','web_app',null
  );
  select action into v_action from public.get_privacy_consent_status(v_user)
   where consent_scope='vision_deepseek';
  if v_action <> 'accepted' then raise exception 'latest Vision consent was not accepted'; end if;

  v_transfer := public.record_ai_data_transfer_event(
    v_user,'deepseek','deepseek-flash','vision','attempted',v_consent,v_correlation
  );
  perform public.record_ai_data_transfer_event(
    v_user,'deepseek','deepseek-flash','vision','succeeded',v_consent,v_correlation
  );
  -- A request that started with valid consent may finish its audit after a concurrent withdrawal.
  perform public.record_ai_data_transfer_event(
    v_user,'deepseek','deepseek-flash','vision','attempted',v_consent,v_race_correlation
  );
  if v_transfer is null then raise exception 'Vision transfer audit did not return an ID'; end if;

  v_failed := false;
  begin
    perform public.record_ai_data_transfer_event(
      v_other,'deepseek','deepseek-flash','vision','attempted',v_consent,v_correlation
    );
  exception when sqlstate '22023' then v_failed := true;
  end;
  if not v_failed then raise exception 'cross-user Vision consent reference was accepted'; end if;

  perform public.record_privacy_consent_event(
    v_user,'vision_deepseek','withdrawn','privacy-2026-01','vision-consent-2026-01','account_settings',null
  );
  select action into v_action from public.get_privacy_consent_status(v_user)
   where consent_scope='vision_deepseek';
  if v_action <> 'withdrawn' then raise exception 'Vision withdrawal did not become current status'; end if;
  perform public.record_ai_data_transfer_event(
    v_user,'deepseek','deepseek-flash','vision','succeeded',v_consent,v_race_correlation
  );
  v_failed := false;
  begin
    perform public.record_ai_data_transfer_event(
      v_user,'deepseek','deepseek-flash','vision','attempted',v_consent,v_correlation
    );
  exception when sqlstate '22023' then v_failed := true;
  end;
  if not v_failed then raise exception 'withdrawn Vision consent was reused'; end if;

  v_request := public.create_privacy_request(v_user,'export',v_request_key);
  v_request_2 := public.create_privacy_request(v_user,'export',v_request_key);
  if (v_request->>'id') <> (v_request_2->>'id')
     or (v_request->>'duplicate') <> 'false'
     or (v_request_2->>'duplicate') <> 'true' then
    raise exception 'privacy request idempotency failed';
  end if;
  v_failed := false;
  begin
    perform public.create_privacy_request(v_user,'deletion',v_request_key);
  exception when unique_violation then v_failed := true;
  end;
  if not v_failed then raise exception 'privacy request idempotency conflict was accepted'; end if;
end;
$$;

do $$
declare
  v_user uuid := 'a31c7e5a-45a1-4bde-8b6c-8f7f95d7a901';
  v_failed boolean := false;
begin
  begin
    update public.privacy_consent_events set action='withdrawn' where user_id=v_user;
  exception when sqlstate '55000' then v_failed := true;
  end;
  if not v_failed then raise exception 'consent journal allowed update'; end if;

  v_failed := false;
  begin
    delete from public.ai_data_transfer_events where user_id=v_user;
  exception when sqlstate '55000' then v_failed := true;
  end;
  if not v_failed then raise exception 'AI transfer journal allowed delete'; end if;
end;
$$;
rollback;
select 'privacy governance migration checks passed' as result;
