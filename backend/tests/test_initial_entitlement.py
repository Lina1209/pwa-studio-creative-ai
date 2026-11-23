from uuid import UUID
import pytest
from app.core.config import Settings
from app.services import initial_entitlement as ent

USER=UUID("11111111-1111-4111-8111-111111111111")

class FakeResponse:
    content=b"{}"
    def __init__(self,data): self.data=data
    def raise_for_status(self): return None
    def json(self): return self.data

class FakeClient:
    def __init__(self,response): self.response=response; self.calls=[]
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def post(self,url,json,headers): self.calls.append((url,json,headers)); return self.response

def cfg(**kwargs):
    return Settings(supabase_url="https://project.example.supabase.co",
      supabase_service_role_key="sb_secret_test_key",**kwargs)

def test_grant_is_disabled_by_default():
    assert ent.grant_initial_free_entitlement(cfg(),user_id=USER) is None

def test_grant_uses_stable_user_scoped_idempotency(monkeypatch):
    client=FakeClient(FakeResponse({"available_credits":100,"reserved_credits":0,"replayed":False}))
    monkeypatch.setattr(ent.httpx,"Client",lambda timeout:client)
    result=ent.grant_initial_free_entitlement(cfg(free_entitlement_policy_code="free_monthly"),user_id=USER)
    assert result=={"replayed":False}
    url,payload,headers=client.calls[0]
    assert url.endswith("/rpc/grant_user_credit_entitlement")
    assert payload["p_user_id"]==str(USER)
    assert payload["p_event_key"]=="initial_wallet_entitlement:v1"
    assert payload["p_source_reference"]=="initial_wallet:"+str(USER)
    assert payload["p_policy_code"]=="free_monthly"
    assert headers["apikey"]=="sb_secret_test_key"

@pytest.mark.parametrize("data",[
    {"available_credits":True,"reserved_credits":0,"replayed":False},
    {"available_credits":-1,"reserved_credits":0,"replayed":False},
    {"available_credits":10,"reserved_credits":0,"replayed":"false"},
    [],
])
def test_invalid_rpc_result_fails_closed(monkeypatch,data):
    client=FakeClient(FakeResponse(data))
    monkeypatch.setattr(ent.httpx,"Client",lambda timeout:client)
    with pytest.raises(ent.EntitlementGrantUnavailable):
        ent.grant_initial_free_entitlement(cfg(free_entitlement_policy_code="free_monthly"),user_id=USER)

def test_unconfigured_policy_never_calls_supabase(monkeypatch):
    def forbidden(*args,**kwargs): raise AssertionError("must not call")
    monkeypatch.setattr(ent.httpx,"Client",forbidden)
    assert ent.grant_initial_free_entitlement(cfg(),user_id=USER) is None
