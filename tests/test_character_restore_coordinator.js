"use strict";
const assert=require("node:assert/strict");
const {createHash}=require("node:crypto");
require("../character-cloud-restore.js");
require("../character-restore-coordinator.js");
const coordinator=global.PWACharacterRestoreCoordinator;
const planner=global.PWACharacterCloudRestore;
const gate={plan:Object.freeze({}),preview:Object.freeze({}),confirmation:Object.freeze({selectedCloudIds:["55555555-5555-4555-8555-555555555555"]}),validateConfirmation:()=>true};
const owner="11111111-1111-4111-8111-111111111111";
const operation="22222222-2222-4222-8222-222222222222";
const asset="33333333-3333-4333-8333-333333333333";
const blobId="44444444-4444-4444-8444-444444444444";
const characterId="55555555-5555-4555-8555-555555555555";
const sourceLocalId="66666666-6666-4666-8666-666666666666";
const localReferenceId=sourceLocalId+"-77777777-7777-4777-8777-777777777777";
const bytes=Buffer.from("fake but deterministic image bytes");
const sha=createHash("sha256").update(bytes).digest("hex");
function makeJournal(){
 let row={ownerId:owner,operationId:operation,state:"planned",revision:1,references:[],lease:null,leaseEpoch:0};
 return {
  async get(o,id){return o===owner&&id===operation?structuredClone(row):null;},
  async acquireLease(o,id){assert.equal(o,owner);assert.equal(id,operation);assert.equal(row.lease,null);row.leaseEpoch++;row.lease={token:"lease-token-"+row.leaseEpoch,epoch:row.leaseEpoch};row.revision++;return structuredClone(row.lease);},
  async renewLease(o,id,lease){assert.equal(o,owner);assert.equal(id,operation);assert.equal(lease.token,row.lease.token);return structuredClone(row.lease);},
  async checkpoint(input){
   assert.equal(input.ownerId,owner);assert.equal(input.operationId,operation);
   assert.equal(input.leaseToken,row.lease.token);assert.equal(input.leaseEpoch,row.lease.epoch);
   assert.equal(input.expectedRevision,row.revision);
   const allowed={planned:["staging"],staging:["staging","ready_to_activate","paused_retryable"],paused_retryable:["staging"]};
   assert.ok(allowed[row.state].includes(input.state),"illegal state transition");
   row={...row,state:input.state,revision:row.revision+1,references:structuredClone(input.references||row.references),lease:row.lease,leaseEpoch:row.leaseEpoch};
   return structuredClone(row);
  },
  async releaseLease(o,id,lease){assert.equal(lease.token,row.lease.token);row.lease=null;row.revision++;return true;},
  inspect(){return structuredClone(row);}
 };
}
const manifest=[{cloudAssetId:asset,characterId,sourceLocalId,localReferenceId,name:"front.png",type:"image/png",expectedSha256:sha,expectedSizeBytes:bytes.length,expectedMimeType:"image/png",width:32,height:24}];
async function issuedGate(){
 const plan=await planner.planRestore({ownerId:owner,existingLocalItems:[],fetchPage:async()=>({items:[{id:characterId,source_local_id:sourceLocalId,version:1,name:"Катти",description:"",created_at:"2026-11-28T00:00:00.000Z",reference_data:{kind:"character",representation:"2d",voice:"",passport:{},referenceImages:[]}}],next_cursor:null})});
 const selected=planner.selectRestorePlan({ownerId:owner,plan,selectedCloudIds:[characterId]});
 const preview=planner.buildRestorePreview({ownerId:owner,plan:selected});
 const confirmation=planner.confirmRestorePreview({ownerId:owner,plan:selected,preview,confirmed:true});
 return {plan:selected,preview,confirmation,validateConfirmation:planner.validateRestoreConfirmation};
}
function adapters({badReadback=false}={}){
 const staged=new Map();
 const good=new Blob([bytes],{type:"image/png"});
 return {
  staged,
  async downloadAsset(){return good;},
  async inspectImage(){return {width:32,height:24};},
  async stageBlob(input){staged.set(input.localStagedBlobId,input.blob);return {localStagedBlobId:input.localStagedBlobId};},
  async readStagedBlob(input){return badReadback?new Blob(["tampered"],{type:"image/png"}):staged.get(input.localStagedBlobId);}
 };
}
(async()=>{
 const journal=makeJournal(),store=adapters(),realGate=await issuedGate();
 const result=await coordinator.stageRestoreReferences({ownerId:owner,operationId:operation,manifest,expectedRevision:1,journal,...realGate,adapters:store});
 assert.equal(result.state,"ready_to_activate");
 assert.equal(result.stagedReferences,1);
 assert.equal(journal.inspect().references[0].state,"verified_staged");
 assert.equal(journal.inspect().references[0].characterId,characterId);
 assert.equal(journal.inspect().references[0].localReferenceId,localReferenceId);
 assert.equal(journal.inspect().lease,null);
 console.log("PASS verified download, staged Blob read-back, durable checkpoint and lease release");
 const mismatchJournal=makeJournal(),mismatchGate=await issuedGate();let mismatchReads=0;
 const guardedJournal={...mismatchJournal,async get(...args){mismatchReads++;return mismatchJournal.get(...args)}};
 const wrongManifest=manifest.map(item=>({...item,characterId:"77777777-7777-4777-8777-777777777777"}));
 await assert.rejects(()=>coordinator.stageRestoreReferences({ownerId:owner,operationId:operation,manifest:wrongManifest,expectedRevision:1,journal:guardedJournal,...mismatchGate,adapters:adapters()}),/outside the explicitly confirmed/);
 assert.equal(mismatchReads,0);assert.equal(mismatchJournal.inspect().state,"planned");
 console.log("PASS real planner confirmation binds coordinator manifest to selected cloud characters before journal access");

 const second=makeJournal(),bad=adapters({badReadback:true});
 await assert.rejects(()=>coordinator.stageRestoreReferences({ownerId:owner,operationId:operation,manifest,expectedRevision:1,journal:second,...gate,adapters:bad}));
 assert.equal(second.inspect().state,"paused_retryable");
 assert.equal(second.inspect().references[0].state,"pending");
 assert.equal(second.inspect().lease,null);
 console.log("PASS tampered staged Blob is rejected and operation remains retryable");

 const third=makeJournal();
 let current=true;
 const switched={...adapters(),async downloadAsset(){current=false;return new Blob([bytes],{type:"image/png"});}};
 await assert.rejects(()=>coordinator.stageRestoreReferences({ownerId:owner,operationId:operation,manifest,expectedRevision:1,journal:third,...gate,adapters:switched,isCurrent:()=>current}));
 assert.equal(third.inspect().state,"staging");
 assert.equal(third.inspect().references[0].state,"pending");
 console.log("PASS account switch fences post-download staging writes");

 const fourth=makeJournal(),checkpointGate=await issuedGate();let valid=true,downloads=0;
 const checkpointJournal={
  ...fourth,
  async checkpoint(input){const result=await fourth.checkpoint(input);if(input.state==="staging"&&input.expectedRevision===2)valid=false;return result;}
 };
 const noDownload={...adapters(),async downloadAsset(){downloads++;return new Blob([bytes],{type:"image/png"});}};
 await assert.rejects(()=>coordinator.stageRestoreReferences({ownerId:owner,operationId:operation,manifest,expectedRevision:1,journal:checkpointJournal,...checkpointGate,validateConfirmation:()=>valid,adapters:noDownload}),/confirmation/);
 assert.equal(downloads,0);
 assert.equal(fourth.inspect().state,"paused_retryable");
 assert.equal(fourth.inspect().lease,null);
 console.log("PASS confirmation expiring during initial durable checkpoint pauses safely before any download");
})().catch(error=>{console.error(error);process.exitCode=1;});
