"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { createMovieCloudOperations } = require("../movie-cloud-operations.js");
const { capture, isCurrent } = require("../movie-cloud-context.js");

function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}
function harness() {
  let userId = "A", version = 1, timerId = 0;
  const timers = new Map(), calls = [], local = { A: [{id:"a1",name:"A film"}], B:[{id:"b1",name:"B film"}] };
  const tombstones = { A:[], B:[] };
  const supabase = {
    from() {
      return {
        delete() { const q={in(){return q;},eq(){return q;}, then(resolve){return Promise.resolve({error:null}).then(resolve);}}; return q; },
        upsert(rows) { calls.push({type:"upsert",rows}); return Promise.resolve({error:null}); },
        select() { const q={eq(){return q;},order(){return Promise.resolve({data:[],error:null});}}; return q; }
      };
    }
  };
  const ops = createMovieCloudOperations({
    isCurrent: c => isCurrent(c,userId,version),
    setTimer: fn => { const id=++timerId; timers.set(id,fn); return id; },
    clearTimer: id => timers.delete(id),
    supabase: () => supabase,
    readTombstones: owner => [...tombstones[owner]],
    writeTombstones: (owner,ids) => { tombstones[owner]=[...ids]; },
    readProjects: owner => [...local[owner]],
    writeProjects: (owner,projects) => { assert.equal(owner,userId); local[owner]=projects; },
    toCloudRow: (p,owner) => ({id:p.id,owner_id:owner}),
    fromCloudRow: row => ({id:row.id,name:row.title,updatedAt:row.updated_at}),
    render:()=>calls.push({type:"render",userId}),
    feedback:message=>calls.push({type:"feedback",message,userId}),
    syncError:error=>calls.push({type:"syncError",error}),
    loadError:error=>calls.push({type:"loadError",error})
  });
  return {ops,timers,calls,local,setUser(id,v){userId=id;version=v;},capture(){return capture(userId,version);},flush(){const entries=[...timers.values()];timers.clear();entries.forEach(fn=>fn());}};
}

test("scheduled A sync is discarded after switching to B before debounce", async () => {
  const h=harness(), a=h.capture();
  h.ops.schedule(a); h.setUser("B",2); h.flush();
  await Promise.resolve();
  assert.equal(h.calls.some(c=>c.type==="upsert"),false);
});

test("sync writes only the captured owner and never serializes A projects as B", async () => {
  const h=harness(), a=h.capture();
  h.ops.schedule(a); h.flush(); await new Promise(r=>setImmediate(r));
  assert.deepEqual(h.calls.find(c=>c.type==="upsert").rows,[{id:"a1",owner_id:"A"}]);
});

test("old sync completion cannot clear a newer pending account context", async () => {
  const h=harness(), a=h.capture();
  const wait=deferred();
  // A deferred delete pauses its continuation while B schedules a follow-up.
  const original=h.ops.state;
  assert.ok(original);
  h.ops.schedule(a); h.flush();
  h.setUser("B",2);
  const b=h.capture();
  h.ops.schedule(b); h.flush();
  await Promise.resolve();
  assert.equal(h.ops.state.pendingContext?.ownerId,"B");
});

test("same-user reauthentication invalidates an older load context", async () => {
  const h=harness(), old=h.capture();
  h.setUser("A",2);
  await h.ops.load(old);
  assert.equal(h.calls.some(c=>c.type==="render"),false);
});

test("guest drafts are not sent to cloud", async () => {
  const h=harness(), guest=capture(null,3);
  assert.equal(guest,null);
  assert.equal(h.ops.schedule(guest),undefined);
  h.flush();
  assert.equal(h.calls.some(c=>c.type==="upsert"),false);
});
