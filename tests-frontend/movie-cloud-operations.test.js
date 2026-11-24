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
   delete(){const q={in(){return q;},eq(){return q;},then(resolve,reject){return (deleteGate?deleteGate.promise:Promise.resolve()).then(()=>({error:null})).then(resolve,reject);}};return q;},
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
 return {ops,timers,calls,local,setUser(id,v){userId=id;version=v;},capture(){return capture(userId,version);},
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
test("cloud project listing is explicitly scoped to the captured owner",async()=>{\n const h=harness(),a=h.capture();await h.ops.load(a);\n const query=h.calls.find(c=>c.type==="select");\n assert.deepEqual(query.filters,[["owner_id","A"],["project_type","movie"]]);\n});\ntest("stale cloud load response after account switch is ignored",async()=>{
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
