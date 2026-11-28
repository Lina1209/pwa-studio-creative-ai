"use strict";
require("../character-cloud-restore.js");
require("../character-local-storage-adapter.js");
const assert=require("node:assert/strict");
const planner=globalThis.PWACharacterCloudRestore;
const adapterFactory=globalThis.PWACharacterLocalStorageAdapter.createCharacterLocalStorageAdapter;
const owner="11111111-1111-4111-8111-111111111111";
const cloudId="22222222-2222-4222-8222-222222222222";
const localId="33333333-3333-4333-8333-333333333333";
const existing={id:"44444444-4444-4444-8444-444444444444",name:"Существующая карточка",kind:"character",description:"не трогать",referenceImages:[]};
const values=new Map();
const storage={getItem:k=>values.has(k)?values.get(k):null,setItem:(k,v)=>values.set(k,String(v))};
const adapter=adapterFactory({storage,ownerId:owner});
adapter.writeLocalItems(owner,[existing]);
const cloudRow={
 id:cloudId,source_local_id:localId,version:1,name:"Катти",description:"Облачное описание",
 reference_data:{kind:"character",representation:"both",voice:"мягкий голос",passport:{face:"зелёные глаза",body:"стройный силуэт",wardrobe:"фиолетовое худи",palette:"рыжий"},referenceImages:[{id:"image-1",name:"katty.png",type:"image/png"}]},
 created_at:"2026-11-28T00:00:00.000Z"
};
(async()=>{
 const plan=await planner.planRestore({ownerId:owner,existingLocalItems:adapter.readLocalItems(owner),fetchPage:async()=>({items:[cloudRow],next_cursor:null})});
 assert.equal(plan.complete,true);
 const result=planner.applyRestorePlan({ownerId:owner,plan,readLocalItems:adapter.readLocalItems,writeLocalItems:adapter.writeLocalItems,isCurrent:()=>true});
 assert.deepEqual(result,{restoredCount:1,totalCount:2});
 const saved=adapter.readLocalItems(owner);
 assert.equal(saved.length,2);
 assert.deepEqual(saved[0],plan.proposedItems[0]);
 assert.deepEqual(saved[1],existing);
 assert.deepEqual(saved[0].referenceImages,[]);
 assert.equal(saved[0].cloudBackup.referenceManifest[0].name,"katty.png");
 assert.equal(saved[0].cloudBackup.characterId,cloudId);
 console.log("PASS end-to-end metadata restore through owner-bound localStorage adapter");
})().catch(error=>{console.error(error);process.exitCode=1;});
