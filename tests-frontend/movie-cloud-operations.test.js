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
   select(){const filters=[];let recorded=false;const record=()=>{if(!recorded){calls.push({type:"select",filters:[...filters]});recorded=true;}};const result=()=>{record();return selectGate?selectGate.promise:Promise.resolve({data:[],error:null});};const q={eq(key,value){filters.push([key,value]);return q;},in(key,values){filters.push([key,values]);return q;},order(){return result();},then(resolve,reject){return result().then(resolve,reject);}};return q;}
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
  fromCloudRow:r=>({...r.settings,id:r.id,name:r.title,updatedAt:r.updated_at}),
  render:()=>calls.push({type:"render",userId}),
  feedback:message=>calls.push({type:"feedback",message,userId}),
  syncError:error=>calls.push({type:"syncError",error}),
  loadError:error=>calls.push({type:"loadError",error})
 });
 return {ops,timers,calls,local,tombstones,setUser(id,v){userId=id;version=v;},capture(){return capture(userId,version);},
  setUpsertGate(g){upsertGate=g;},setSelectGate(g){selectGate=g;},setDeleteGate(g){deleteGate=g;},setTombstones(owner,ids){tombstones[owner]=[...ids];},
  flush(){const batch=[...timers.values()];timers.clear();batch.forEach(fn=>fn());}};
}
test("oversized cloud project is rejected before upsert",async()=>{
 const h=harness();
 h.local.A=[{id:"large",name:"Large film",payload:"x".repeat(270*1024)}];
 // The production adapter serializes the full project into settings.
 const original=h.ops;
 const {createMovieCloudOperations}=require("../movie-cloud-operations.js");
 const calls=[];
 const ops=createMovieCloudOperations({
  isCurrent:c=>isCurrent(c,"A",1),setTimer:fn=>{calls.push({type:"timer",fn});return 1;},clearTimer:()=>{},
  supabase:()=>({from:()=>({upsert:async rows=>{calls.push({type:"upsert",rows});return{error:null};}})}),
  readTombstones:()=>[],writeTombstones:()=>{},readProjects:()=>h.local.A,
  writeProjects:()=>{},toCloudRow:(p,owner)=>({id:p.id,owner_id:owner,project_type:"movie",settings:p}),
  fromCloudRow:r=>r,render:()=>{},feedback:()=>{},syncError:e=>calls.push({type:"error",message:e.message}),loadError:()=>{}
 });
 ops.schedule(capture("A",1));calls.find(c=>c.type==="timer").fn();await new Promise(r=>setImmediate(r));
 assert.equal(calls.some(c=>c.type==="upsert"),false);
 assert.match(calls.find(c=>c.type==="error").message,/256 КиБ/);
});
test("malformed cloud project settings are rejected before upsert",async()=>{
 const {createMovieCloudOperations}=require("../movie-cloud-operations.js");
 const calls=[];
 const ops=createMovieCloudOperations({
  isCurrent:c=>isCurrent(c,"A",1),setTimer:fn=>{calls.push({type:"timer",fn});return 1;},clearTimer:()=>{},
  supabase:()=>({from:()=>({upsert:async rows=>{calls.push({type:"upsert",rows});return{error:null};}})}),
  readTombstones:()=>[],writeTombstones:()=>{},readProjects:()=>[{id:"bad"}],writeProjects:()=>{},
  toCloudRow:(p,owner)=>({id:p.id,owner_id:owner,project_type:"movie",settings:"not-an-object"}),
  fromCloudRow:r=>r,render:()=>{},feedback:()=>{},syncError:e=>calls.push({type:"error",message:e.message}),loadError:()=>{}
 });
 ops.schedule(capture("A",1));calls.find(c=>c.type==="timer").fn();await new Promise(r=>setImmediate(r));
 assert.equal(calls.some(c=>c.type==="upsert"),false);
 assert.match(calls.find(c=>c.type==="error").message,/структура/i);
});
test("local project storage failure aborts cloud upsert and reports sync error",async()=>{
 const calls=[];
 const ops=createMovieCloudOperations({
  isCurrent:c=>isCurrent(c,"A",1),
  setTimer:fn=>{calls.push({type:"timer",fn});return 1;},clearTimer:()=>{},
  supabase:()=>({from:()=>({upsert:async rows=>{calls.push({type:"upsert",rows});return{error:null};}})}),
  readTombstones:()=>[],writeTombstones:()=>true,
  readProjects:()=>[{id:"local-a",name:"Draft"}],
  writeProjects:()=>{throw new Error("QuotaExceededError");},
  toCloudRow:(p,owner)=>({id:p.id,owner_id:owner,project_type:"movie",settings:p}),
  fromCloudRow:r=>r,render:()=>{},feedback:()=>calls.push({type:"feedback"}),
  syncError:e=>calls.push({type:"syncError",message:e.message}),loadError:()=>{}
 });
 ops.schedule(capture("A",1));calls.find(x=>x.type==="timer").fn();
 await new Promise(r=>setImmediate(r));
 assert.equal(calls.some(x=>x.type==="upsert"),false);
 assert.equal(calls.some(x=>x.type==="feedback"),false);
 assert.match(calls.find(x=>x.type==="syncError").message,/QuotaExceededError/);
});
test("tombstone cleanup storage failure never reports sync success",async()=>{
 const h=harness(),id="123e4567-e89b-42d3-a456-426614174000";
 h.setTombstones("A",[id]);
 // Simulate localStorage quota/security failure after the cloud delete succeeds.
 const originalWrite=h.tombstones;
 const ops=createMovieCloudOperations({
  isCurrent:c=>isCurrent(c,"A",1),setTimer:fn=>{h.timers.set(99,fn);return 99;},clearTimer:id=>h.timers.delete(id),
  supabase:()=>({from:()=>({delete(){const q={in(){return q;},eq(){return q;},then(resolve){return Promise.resolve({error:null}).then(resolve);}};return q;}})}),
  readTombstones:()=>[...originalWrite.A],writeTombstones:()=>false,readProjects:()=>originalWrite.A.map(id=>({id})),
  writeProjects:()=>{},toCloudRow:(p,owner)=>({id:p.id,owner_id:owner,project_type:"movie",settings:p}),
  fromCloudRow:r=>r,render:()=>{},feedback:()=>h.calls.push({type:"feedback"}),syncError:e=>h.calls.push({type:"syncError",message:e.message}),loadError:()=>{}
 });
 ops.schedule(capture("A",1));h.timers.get(99)();await new Promise(r=>setImmediate(r));
 assert.equal(h.calls.some(c=>c.type==="feedback"),false);
 assert.equal(h.calls.some(c=>c.type==="syncError"),true);
 assert.deepEqual(originalWrite.A,[id]);
});
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

test("local project read failure aborts cloud upsert and reports sync error",async()=>{
 const calls=[];
 const ops=createMovieCloudOperations({
  isCurrent:c=>isCurrent(c,"A",1),setTimer:fn=>{calls.push({type:"timer",fn});return 1;},clearTimer:()=>{},
  supabase:()=>({from:()=>({upsert:async rows=>{calls.push({type:"upsert",rows});return{error:null};}})}),
  readTombstones:()=>[],writeTombstones:()=>true,
  readProjects:()=>{throw new Error("localStorage access denied");},
  writeProjects:()=>{calls.push({type:"writeLocal"});},
  toCloudRow:(p,owner)=>({id:p.id,owner_id:owner,project_type:"movie",settings:p}),
  fromCloudRow:r=>r,render:()=>{},feedback:()=>calls.push({type:"feedback"}),
  syncError:e=>calls.push({type:"syncError",message:e.message}),loadError:()=>{}
 });
 ops.schedule(capture("A",1));calls.find(x=>x.type==="timer").fn();await new Promise(r=>setImmediate(r));
 assert.equal(calls.some(x=>x.type==="upsert"),false);
 assert.equal(calls.some(x=>x.type==="writeLocal"),false);
 assert.equal(calls.some(x=>x.type==="feedback"),false);
 assert.match(calls.find(x=>x.type==="syncError").message,/localStorage access denied/);
});

test("local project read failure prevents cloud load from overwriting device state",async()=>{
 const calls=[];
 const ops=createMovieCloudOperations({
  isCurrent:c=>isCurrent(c,"A",1),setTimer:fn=>{calls.push({type:"timer",fn});return 1;},clearTimer:()=>{},
  supabase:()=>({from:()=>({select(){const q={eq(){return q;},order(){calls.push({type:"select"});return Promise.resolve({data:[{id:"cloud-a",title:"Cloud",updated_at:"2026-01-01"}],error:null});}};return q;}})}),
  readTombstones:()=>[],writeTombstones:()=>true,
  readProjects:()=>{throw new Error("local JSON is corrupt");},
  writeProjects:()=>calls.push({type:"writeLocal"}),toCloudRow:(p,owner)=>({id:p.id,owner_id:owner}),
  fromCloudRow:r=>({id:r.id,name:r.title,updatedAt:r.updated_at}),
  render:()=>calls.push({type:"render"}),feedback:()=>calls.push({type:"feedback"}),
  syncError:()=>{},loadError:e=>calls.push({type:"loadError",message:e.message})
 });
 await ops.load(capture("A",1));
 assert.equal(calls.some(x=>x.type==="writeLocal"),false);
 assert.equal(calls.some(x=>x.type==="render"),false);
 assert.equal(calls.some(x=>x.type==="feedback"),false);
 assert.match(calls.find(x=>x.type==="loadError").message,/local JSON is corrupt/);
});


test("deletion queue read failure aborts sync before cloud upsert",async()=>{
 const calls=[];
 const ops=createMovieCloudOperations({
  isCurrent:c=>isCurrent(c,"A",1),setTimer:fn=>{calls.push({type:"timer",fn});return 1;},clearTimer:()=>{},
  supabase:()=>({from:()=>({upsert:async rows=>{calls.push({type:"upsert",rows});return{error:null};}})}),
  readTombstones:()=>{throw new Error("deletion queue unavailable");},writeTombstones:()=>true,
  readProjects:()=>[{id:"local-a"}],writeProjects:()=>calls.push({type:"writeLocal"}),
  toCloudRow:(p,owner)=>({id:p.id,owner_id:owner}),fromCloudRow:r=>r,
  render:()=>calls.push({type:"render"}),feedback:()=>calls.push({type:"feedback"}),
  syncError:e=>calls.push({type:"syncError",message:e.message}),loadError:()=>{}
 });
 ops.schedule(capture("A",1));calls.find(x=>x.type==="timer").fn();await new Promise(r=>setImmediate(r));
 assert.equal(calls.some(x=>x.type==="upsert"||x.type==="writeLocal"||x.type==="feedback"),false);
 assert.match(calls.find(x=>x.type==="syncError").message,/deletion queue unavailable/);
});

test("deletion queue read failure prevents cloud load from overwriting local projects",async()=>{
 const calls=[];
 const ops=createMovieCloudOperations({
  isCurrent:c=>isCurrent(c,"A",1),setTimer:fn=>{calls.push({type:"timer",fn});return 1;},clearTimer:()=>{},
  supabase:()=>({from:()=>({select(){const q={eq(){return q;},order(){return Promise.resolve({data:[{id:"cloud-a",title:"Cloud",updated_at:"2026-01-01"}],error:null});}};return q;}})}),
  readTombstones:()=>{throw new Error("deletion queue unavailable");},writeTombstones:()=>true,
  readProjects:()=>[{id:"local-a"}],writeProjects:()=>calls.push({type:"writeLocal"}),
  toCloudRow:(p,owner)=>({id:p.id,owner_id:owner}),fromCloudRow:r=>({id:r.id}),
  render:()=>calls.push({type:"render"}),feedback:()=>calls.push({type:"feedback"}),
  syncError:()=>{},loadError:e=>calls.push({type:"loadError",message:e.message})
 });
 await ops.load(capture("A",1));
 assert.equal(calls.some(x=>x.type==="writeLocal"||x.type==="render"||x.type==="feedback"),false);
 assert.match(calls.find(x=>x.type==="loadError").message,/deletion queue unavailable/);
});


test("local project storage write failure during cloud load prevents render and success feedback",async()=>{
 const calls=[];
 const ops=createMovieCloudOperations({
  isCurrent:c=>isCurrent(c,"A",1),
  setTimer:fn=>{calls.push({type:"timer",fn});return 1;},clearTimer:()=>{},
  supabase:()=>({from:()=>({select(){const q={eq(){return q;},order(){return Promise.resolve({data:[{id:"cloud-a",title:"Cloud draft",updated_at:"2026-01-01"}],error:null});}};return q;}})}),
  readTombstones:()=>[],writeTombstones:()=>true,
  readProjects:()=>[{id:"local-a",name:"Local draft"}],
  writeProjects:()=>{calls.push({type:"writeAttempt"});throw new Error("QuotaExceededError: storage full");},
  toCloudRow:(p,owner)=>({id:p.id,owner_id:owner,project_type:"movie",settings:p}),
  fromCloudRow:r=>({id:r.id,name:r.title,updatedAt:r.updated_at}),
  render:()=>calls.push({type:"render"}),
  feedback:()=>calls.push({type:"feedback"}),
  syncError:()=>{},loadError:e=>calls.push({type:"loadError",message:e.message})
 });
 await ops.load(capture("A",1));
 assert.equal(calls.some(x=>x.type==="writeAttempt"),true);
 assert.equal(calls.some(x=>x.type==="render"||x.type==="feedback"||x.type==="timer"),false);
 assert.match(calls.find(x=>x.type==="loadError").message,/QuotaExceededError/);
});

test("valid newer local project is preserved when cloud copy is older",async()=>{
 const h=harness();
 h.local.A=[{id:"same",name:"Local newer",updatedAt:"2026-11-20T12:00:00Z",versions:[{savedAt:"2026-11-20T11:00:00Z"}]}];
 const gate=deferred(); h.setSelectGate(gate); gate.resolve({data:[{id:"same",title:"Cloud older",updated_at:"2026-11-19T12:00:00Z"}],error:null});
 await h.ops.load(h.capture());
 assert.equal(h.local.A[0].name,"Local newer");
 assert.equal(h.local.A[0].versions.length,1);
});
test("valid newer cloud project replaces older local copy with full cloud payload",async()=>{
 const h=harness();
 h.local.A=[{id:"same",name:"Local older",updatedAt:"2026-11-19T12:00:00Z"}];
 const gate=deferred(); h.setSelectGate(gate); gate.resolve({data:[{id:"same",title:"Cloud newer",updated_at:"2026-11-20T12:00:00Z",settings:{versions:[{savedAt:"2026-11-20T11:00:00Z"}]}}],error:null});
 await h.ops.load(h.capture());
 assert.equal(h.local.A[0].name,"Cloud newer");
 assert.equal(h.local.A[0].versions.length,1);
});
test("invalid cloud timestamp never overwrites a valid local project",async()=>{
 const h=harness();
 h.local.A=[{id:"same",name:"Local valid",updatedAt:"2026-11-20T12:00:00Z"}];
 const gate=deferred(); h.setSelectGate(gate); gate.resolve({data:[{id:"same",title:"Cloud malformed",updated_at:"not-a-date"}],error:null});
 await h.ops.load(h.capture());
 assert.equal(h.local.A[0].name,"Local valid");
});
test("valid cloud timestamp replaces local project with missing or invalid timestamp",async()=>{
 for (const updatedAt of [undefined,"not-a-date"]) {
  const h=harness();
  h.local.A=[{id:"same",name:"Local undated",updatedAt}];
  const gate=deferred(); h.setSelectGate(gate); gate.resolve({data:[{id:"same",title:"Cloud dated",updated_at:"2026-11-20T12:00:00Z"}],error:null});
  await h.ops.load(h.capture());
  assert.equal(h.local.A[0].name,"Cloud dated");
 }
});
test("equal timestamps preserve local draft to avoid losing unsynced edits",async()=>{
 const h=harness();
 h.local.A=[{id:"same",name:"Local tie",updatedAt:"2026-11-20T12:00:00Z"}];
 const gate=deferred(); h.setSelectGate(gate); gate.resolve({data:[{id:"same",title:"Cloud tie",updated_at:"2026-11-20T12:00:00Z"}],error:null});
 await h.ops.load(h.capture());
 assert.equal(h.local.A[0].name,"Local tie");
});

test("sync does not overwrite a newer cloud project with a stale local draft",async()=>{
 const h=harness();
 h.local.A=[{id:"same",name:"Local stale",updatedAt:"2026-11-19T12:00:00Z"}];
 const gate=deferred();h.setSelectGate(gate);
 h.ops.schedule(h.capture());h.flush();await Promise.resolve();
 gate.resolve({data:[{id:"same",title:"Cloud newer",updated_at:"2026-11-20T12:00:00Z",settings:{versions:[{savedAt:"2026-11-20T11:00:00Z"}]}}],error:null});
 await new Promise(r=>setImmediate(r));
 assert.equal(h.calls.some(c=>c.type==="upsert"),false);
 assert.equal(h.local.A[0].name,"Cloud newer");
 assert.equal(h.local.A[0].versions.length,1);
});
test("account switch during cloud conflict preflight aborts stale sync before local write or upsert",async()=>{
 const h=harness(),gate=deferred();
 h.local.A=[{id:"same",name:"A draft",updatedAt:"2026-11-19T12:00:00Z"}];
 h.setSelectGate(gate);
 h.ops.schedule(h.capture());h.flush();await Promise.resolve();
 h.setUser("B",2);
 gate.resolve({data:[],error:null});
 await new Promise(r=>setImmediate(r));
 assert.equal(h.calls.some(c=>c.type==="upsert"),false);
 assert.equal(h.calls.some(c=>c.type==="writeLocal"&&c.owner==="B"),false);
});
