"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const {createMovieCloudOperations}=require("../movie-cloud-operations.js");
const {capture,isCurrent}=require("../movie-cloud-context.js");
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};}
function harness(){
 let userId="A",version=1,nextTimer=0;
 const timers=new Map(),calls=[],local={A:[{id:"a1",name:"A film"}],B:[{id:"b1",name:"B film"}]},tombstones={A:[],B:[]};
 let upsertGate=null,selectGate=null,deleteGate=null;
 const supabase={from(){
  return {
   delete(){const filters=[],q={in(column,values){filters.push([column,values]);return q;},eq(key,value){filters.push([key,value]);return q;},then(resolve,reject){calls.push({type:"delete",filters});return (deleteGate?deleteGate.promise:Promise.resolve()).then(result=>result||({error:null})).then(resolve,reject);}};return q;},
   upsert(rows){calls.push({type:"upsert",rows});return (upsertGate?upsertGate.promise:Promise.resolve()).then(()=>({error:null}));},
   select(){const filters=[];const q={eq(key,value){filters.push([key,value]);return q;},order(){calls.push({type:"select",filters});return selectGate?selectGate.promise:Promise.resolve({data:[],error:null});}};return q;}
  };
 }};
 const ops=createMovieCloudOperations({
  isCurrent:c=>isCurrent(c,userId,version),
  setTimer:(fn)=>{const id=++nextTimer;timers.set(id,fn);return id;},
  clearTimer:id=>timers.delete(id),
  supabase:()=>supabase,
  readTombstones:owner=>[...tombstones[owner]],
  writeTombstones:(owner,ids)=>{tombstones[owner]=[...ids];},
  readProjects:owner=>[...local[owner]],
  writeProjects:(owner,projects)=>{local[owner]=projects;calls.push({type:"writeLocal",owner});},
  toCloudRow:(p,owner)=>({id:p.id,owner_id:owner}),
  fromCloudRow:r=>({id:r.id,name:r.title,updatedAt:r.updated_at}),
  render:()=>calls.push({type:"render",userId}),
  feedback:message=>calls.push({type:"feedback",message,userId}),
  syncError:error=>calls.push({type:"syncError",error}),
  loadError:error=>calls.push({type:"loadError",error})
 });
 return {ops,timers,calls,local,tombstones,setUser(id,v){userId=id;version=v;},capture(){return capture(userId,version);},
  setUpsertGate(g){upsertGate=g;},setSelectGate(g){selectGate=g;},setDeleteGate(g){deleteGate=g;},setTombstones(owner,ids){tombstones[owner]=[...ids];},
  flush(){const batch=[...timers.values()];timers.clear();batch.forEach(fn=>fn());}};
}
test("scheduled A sync is discarded after switching to B before debounce",async()=>{
 const h=harness(),a=h.capture();h.ops.schedule(a);h.setUser("B",2);h.flush();await new Promise(r=>setImmediate(r));
 assert.equal(h.calls.some(c=>c.type==="upsert"),false);
});
test("A upsert keeps A owner even if the session changes while request is pending",async()=>{
 const h=harness(),gate=deferred();h.setUpsertGate(gate);const a=h.capture();
 h.ops.schedule(a);h.flush();await new Promise(r=>setImmediate(r));
 assert.deepEqual(h.calls.find(c=>c.type==="upsert").rows,[{id:"a1",owner_id:"A"}]);
 h.setUser("B",2);gate.resolve();await new Promise(r=>setImmediate(r));
 assert.equal(h.calls.some(c=>c.type==="feedback"&&c.userId==="B"),false);
});
test("A completion cannot clear or replace B's pending queue context",async()=>{
 const h=harness(),gate=deferred();h.setUpsertGate(gate);const a=h.capture();
 h.ops.schedule(a);h.flush();await new Promise(r=>setImmediate(r));
 h.setUser("B",2);const b=h.capture();h.ops.schedule(b);h.flush();
 assert.equal(h.ops.state.pendingContext,b);
 gate.resolve();await new Promise(r=>setImmediate(r));
 assert.equal(h.ops.state.syncingContext,null);
 assert.equal(h.ops.state.pendingContext,null);
 assert.equal([...h.timers.values()].length,1);
});
test("cloud project listing is explicitly scoped to the captured owner",async()=>{
 const h=harness(),a=h.capture();await h.ops.load(a);
 const query=h.calls.find(c=>c.type==="select");
 assert.deepEqual(query.filters,[["owner_id","A"],["project_type","movie"]]);
});
test("stale cloud load response after account switch is ignored",async()=>{
 const h=harness(),gate=deferred();h.setSelectGate(gate);const a=h.capture();
 const loading=h.ops.load(a);await Promise.resolve();h.setUser("B",2);
 gate.resolve({data:[{id:"from-a",title:"A cloud",updated_at:"2026-01-01"}],error:null});
 await loading;
 assert.equal(h.calls.some(c=>c.type==="render"),false);
 assert.equal(h.local.B[0].id,"b1");
});
test("same-user reauthentication invalidates an older load generation",async()=>{
 const h=harness(),gate=deferred(),old=h.capture();h.setSelectGate(gate);
 const loading=h.ops.load(old);await Promise.resolve();h.setUser("A",2);
 gate.resolve({data:[{id:"stale",title:"stale",updated_at:"2026-01-01"}],error:null});await loading;
 assert.equal(h.calls.some(c=>c.type==="render"),false);
});
test("guest drafts have no cloud context and cannot be uploaded",async()=>{
 const h=harness();assert.equal(capture(null,3),null);assert.equal(h.ops.schedule(null),undefined);
 h.flush();assert.equal(h.calls.some(c=>c.type==="upsert"),false);
});

test("A delete finishing after account switch cannot continue into B local state",async()=>{
 const h=harness(),gate=deferred();h.setDeleteGate(gate);h.setTombstones("A",["123e4567-e89b-42d3-a456-426614174000"]);
 const a=h.capture();h.ops.schedule(a);h.flush();await Promise.resolve();
 h.setUser("B",2);gate.resolve();await new Promise(r=>setImmediate(r));
 assert.equal(h.calls.some(c=>c.type==="upsert"),false);
 assert.equal(h.calls.some(c=>c.type==="writeLocal"&&c.owner==="B"),false);
 assert.equal(h.local.B[0].id,"b1");
});


test("tombstone deletion is scoped to captured owner and movie type",async()=>{
 const h=harness(),id="123e4567-e89b-42d3-a456-426614174000";
 h.setTombstones("A",[id]);
 const a=h.capture();h.ops.schedule(a);h.flush();await new Promise(r=>setImmediate(r));
 const deletion=h.calls.find(c=>c.type==="delete");
 assert.deepEqual(deletion.filters,[["id",[id]],["owner_id","A"],["project_type","movie"]]);
});

test("failed cloud deletion preserves tombstone and never reports success",async()=>{
 const h=harness(),id="123e4567-e89b-42d3-a456-426614174000",gate=deferred();
 h.setDeleteGate(gate);h.setTombstones("A",[id]);
 const a=h.capture();h.ops.schedule(a);h.flush();await Promise.resolve();
 gate.resolve({error:new Error("delete denied")});
 await new Promise(r=>setImmediate(r));
 assert.equal(h.calls.some(c=>c.type==="upsert"),false);
 assert.equal(h.calls.some(c=>c.type==="feedback"),false);
 assert.equal(h.calls.some(c=>c.type==="syncError"),true);
});


test("failed tombstone cleanup during cloud load keeps tombstone and local project state",async()=>{
 const h=harness(),id="123e4567-e89b-42d3-a456-426614174000",gate=deferred();
 h.setTombstones("A",[id]);h.setDeleteGate(gate);
 const loading=h.ops.load(h.capture());
 await Promise.resolve();await Promise.resolve();
 gate.resolve({error:new Error("cleanup denied")});
 await loading;
 assert.deepEqual(h.calls.filter(c=>c.type==="delete")[0].filters,[["id",[id]],["owner_id","A"],["project_type","movie"]]);
 assert.equal(h.calls.some(c=>c.type==="writeLocal"),false);
 assert.deepEqual(h.local.A,[{id:"a1",name:"A film"}]);
 assert.deepEqual(h.tombstones.A,[id]);
 assert.equal(h.calls.some(c=>c.type==="loadError"),true);
});

test("successful tombstone cleanup during cloud load clears only captured owner's tombstone",async()=>{
 const h=harness(),id="123e4567-e89b-42d3-a456-426614174000";
 h.setTombstones("A",[id]);
 await h.ops.load(h.capture());
 assert.equal(h.calls.some(c=>c.type==="delete"),true);
 assert.equal(h.calls.some(c=>c.type==="render"),true);
 assert.deepEqual(h.tombstones.A,[]);
});


test("cloud load cleanup preserves tombstones created while deletion is in flight",async()=>{
 const h=harness(),oldId="123e4567-e89b-42d3-a456-426614174000",newId="223e4567-e89b-42d3-a456-426614174000",gate=deferred();
 h.setTombstones("A",[oldId]);h.setDeleteGate(gate);
 const loading=h.ops.load(h.capture());
 await Promise.resolve();await Promise.resolve();
 h.setTombstones("A",[oldId,newId]);
 gate.resolve({error:null});
 await loading;
 assert.deepEqual(h.tombstones.A,[newId]);
 assert.deepEqual(h.calls.find(c=>c.type==="delete").filters,[["id",[oldId]],["owner_id","A"],["project_type","movie"]]);
});


test("cloud load does not reintroduce a new tombstone created while cleanup is in flight",async()=>{
 const h=harness(),oldId="123e4567-e89b-42d3-a456-426614174000",newId="223e4567-e89b-42d3-a456-426614174000",gate=deferred();
 h.local.A.push({id:newId,name:"Locally deleted film"});
 h.setTombstones("A",[oldId]);h.setDeleteGate(gate);
 const loading=h.ops.load(h.capture());
 await Promise.resolve();await Promise.resolve();
 h.setTombstones("A",[oldId,newId]);
 gate.resolve({error:null});
 await loading;
 assert.deepEqual(h.tombstones.A,[newId]);
 assert.equal(h.local.A.some(project=>project.id===newId),false);
 assert.equal(h.calls.some(c=>c.type==="render"),true);
});


test("sync does not re-upload a new tombstone created while cloud deletion is in flight",async()=>{
 const h=harness(),oldId="123e4567-e89b-42d3-a456-426614174000",newId="223e4567-e89b-42d3-a456-426614174000",gate=deferred();
 h.local.A.push({id:newId,name:"Deleted during sync"});
 h.setTombstones("A",[oldId]);h.setDeleteGate(gate);
 h.ops.schedule(h.capture());h.flush();
 await Promise.resolve();await Promise.resolve();
 h.setTombstones("A",[oldId,newId]);
 gate.resolve({error:null});
 await new Promise(r=>setImmediate(r));
 const upsert=h.calls.find(c=>c.type==="upsert");
 assert.deepEqual(upsert.rows,[{id:"a1",owner_id:"A"}]);
 assert.deepEqual(h.tombstones.A,[newId]);
});


test("a stale A cloud load does not block B from starting and applying its own load",async()=>{
 const h=harness(),gateA=deferred(),gateB=deferred();
 h.setSelectGate(gateA);
 const loadingA=h.ops.load(h.capture());
 await Promise.resolve();
 h.setUser("B",2);h.setSelectGate(gateB);
 const loadingB=h.ops.load(h.capture());
 await Promise.resolve();
 gateB.resolve({data:[{id:"b-cloud",title:"B cloud",updated_at:"2026-02-01"}],error:null});
 await loadingB;
 assert.equal(h.local.B.some(project=>project.id==="b-cloud"),true);
 gateA.resolve({data:[{id:"a-stale",title:"A stale",updated_at:"2026-03-01"}],error:null});
 await loadingA;
 assert.equal(h.local.B.some(project=>project.id==="a-stale"),false);
 assert.equal(h.local.A.some(project=>project.id==="a-stale"),false);
});


test("a deletion queued during an in-flight upsert is processed by the follow-up sync",async()=>{
 const h=harness(),gate=deferred(),deletedId="323e4567-e89b-42d3-a456-426614174000";
 h.local.A.push({id:deletedId,name:"Deleted during upload"});
 h.setUpsertGate(gate);
 const context=h.capture();
 h.ops.schedule(context);h.flush();
 await new Promise(r=>setImmediate(r));
 const firstUpsert=h.calls.find(c=>c.type==="upsert");
 assert.equal(firstUpsert.rows.some(row=>row.id===deletedId),true);
 h.setTombstones("A",[deletedId]);
 h.ops.schedule(context);h.flush();
 gate.resolve();
 await new Promise(r=>setImmediate(r));
 assert.equal([...h.timers.values()].length,1);
 h.flush();
 await new Promise(r=>setImmediate(r));
 const deletions=h.calls.filter(c=>c.type==="delete");
 assert.deepEqual(deletions[0].filters,[["id",[deletedId]],["owner_id","A"],["project_type","movie"]]);
 const upserts=h.calls.filter(c=>c.type==="upsert");
 assert.equal(upserts.length,2);
 assert.equal(upserts[1].rows.some(row=>row.id===deletedId),false);
 assert.deepEqual(h.tombstones.A,[]);
});
