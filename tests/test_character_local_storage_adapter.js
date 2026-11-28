"use strict";
require("../character-local-storage-adapter.js");
const assert = require("node:assert/strict");
const adapterFactory = globalThis.PWACharacterLocalStorageAdapter.createCharacterLocalStorageAdapter;
const owner = "156e5aa7-f13a-468c-99f0-e8fa13107ac7";
const other = "256e5aa7-f13a-468c-99f0-e8fa13107ac7";
const key = "pwa-studio-character-library-v1:" + owner;
const values = new Map();
const storage = {
  getItem:k=>values.has(k)?values.get(k):null,
  setItem:(k,v)=>values.set(k,String(v))
};
const local=[{id:"local-1",name:"Локальный персонаж",referenceImages:[{id:"blob-1"}]}];
const adapter=adapterFactory({storage,ownerId:owner});
adapter.writeLocalItems(owner,local);
assert.deepEqual(adapter.readLocalItems(owner),local);
assert.equal(adapter.storageKey,key);
assert.throws(()=>adapter.readLocalItems(other),/owner mismatch/);
assert.throws(()=>adapter.writeLocalItems(other,[]),/owner mismatch/);
assert.equal(values.has("pwa-studio-character-library-v1:"+other),false);
assert.throws(()=>adapterFactory({storage,ownerId:owner,isCurrent:()=>false}),/not current/);
values.set(key,"{broken");
assert.throws(()=>adapter.readLocalItems(owner),/JSON is corrupted/);
values.set(key,JSON.stringify([{id:"same",name:"A"},{id:"same",name:"B"}]));
assert.throws(()=>adapter.readLocalItems(owner),/invalid or duplicate/);
values.set(key,JSON.stringify(local));
const before=values.get(key);
const quotaStorage={getItem:storage.getItem,setItem:()=>{throw new Error("quota");}};
const quotaAdapter=adapterFactory({storage:quotaStorage,ownerId:owner});
assert.throws(()=>quotaAdapter.writeLocalItems(owner,[{id:"new",name:"New"}]),/quota/);
assert.equal(values.get(key),before);
let current=true;
const fenced=adapterFactory({storage,ownerId:owner,isCurrent:()=>current});
current=false;
assert.throws(()=>fenced.readLocalItems(owner),/Account changed/);
console.log("PASS owner-bound Character Library localStorage adapter contract");
