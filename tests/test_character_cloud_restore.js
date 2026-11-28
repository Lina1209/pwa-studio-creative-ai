const assert = require("node:assert/strict");
require("../character-cloud-restore.js");
const planner = globalThis.PWACharacterCloudRestore;
const owner = "11111111-1111-4111-8111-111111111111";
const cloudId = "22222222-2222-4222-8222-222222222222";
const localId = "33333333-3333-4333-8333-333333333333";
const localId2 = "44444444-4444-4444-8444-444444444444";
const row = (id, sourceId, overrides={}) => ({
  id, source_local_id:sourceId, version:1, name:"Катти", description:"Описание",
  reference_data:{kind:"character",representation:"both",voice:"",passport:{face:"глаза",body:"силуэт",wardrobe:"худи",palette:"рыжий"},referenceImages:[{id:"ref-local-1",name:"front.png",type:"image/png"}]},
  created_at:"2026-11-28T00:00:00.000Z", ...overrides
});
const page = (items,next_cursor=null) => ({items,next_cursor});
const run = async (name, fn) => { await fn(); process.stdout.write("PASS "+name+"\n"); };
(async()=>{
  await run("fetches every page and produces local-ID-preserving metadata plan",async()=>{
    const calls=[];
    const pages=[page([row(cloudId,localId)],"cursor-1"),page([row("55555555-5555-4555-8555-555555555555",localId2)])];
    const plan=await planner.planRestore({ownerId:owner,existingLocalItems:[],fetchPage:async cursor=>{calls.push(cursor);return pages[calls.length-1];}});
    assert.deepEqual(calls,[null,"cursor-1"]);
    assert.equal(plan.complete,true);
    assert.equal(plan.pagesRead,2);
    assert.equal(plan.cloudCount,2);
    assert.equal(plan.proposedItems.length,2);
    assert.equal(plan.proposedItems[0].id,localId);
    assert.equal(plan.proposedItems[0].cloudBackup.characterId,cloudId);
    assert.deepEqual(plan.proposedItems[0].referenceImages,[]);
    assert.equal(plan.proposedItems[0].cloudBackup.referenceManifest[0].name,"front.png");
  });
  await run("identical local passport is unchanged and never overwritten",async()=>{
    const local={id:localId,name:"Катти",description:"Описание",kind:"character",representation:"both",voice:"",passport:{face:"глаза",body:"силуэт",wardrobe:"худи",palette:"рыжий"},referenceImages:[],cloudBackup:{characterId:cloudId}};
    const snapshot=JSON.stringify(local);
    const plan=await planner.planRestore({ownerId:owner,existingLocalItems:[local],fetchPage:async()=>page([row(cloudId,localId,{reference_data:{kind:"character",representation:"both",voice:"",passport:local.passport,referenceImages:[]}})])});
    assert.equal(plan.unchanged.length,1);
    assert.equal(plan.proposedItems.length,0);
    assert.equal(JSON.stringify(local),snapshot);
  });
  await run("restored metadata manifest remains unchanged without local image Blobs",async()=>{
    const manifest=[{id:"ref-local-1",name:"front.png",type:"image/png"}];
    const local={id:localId,name:"Катти",description:"Описание",kind:"character",representation:"both",voice:"",passport:{face:"глаза",body:"силуэт",wardrobe:"худи",palette:"рыжий"},referenceImages:[],cloudBackup:{characterId:cloudId,version:1,referenceManifest:manifest}};
    const plan=await planner.planRestore({ownerId:owner,existingLocalItems:[local],fetchPage:async()=>page([row(cloudId,localId)])});
    assert.equal(plan.unchanged.length,1);
    assert.equal(plan.conflicts.length,0);
  });
  await run("restore planning uses a stable local snapshot across awaits",async()=>{
    const local={id:localId,name:"Катти",description:"Описание",kind:"character",representation:"both",voice:"",passport:{face:"глаза",body:"силуэт",wardrobe:"худи",palette:"рыжий"},referenceImages:[],cloudBackup:{characterId:cloudId}};
    const plan=await planner.planRestore({ownerId:owner,existingLocalItems:[local],fetchPage:async()=>{local.name="edited while fetching";return page([row(cloudId,localId,{reference_data:{kind:"character",representation:"both",voice:"",passport:{face:"глаза",body:"силуэт",wardrobe:"худи",palette:"рыжий"},referenceImages:[]}})]);}});
    assert.equal(plan.unchanged.length,1);
    assert.equal(local.name,"edited while fetching");
  });
  await run("different local content becomes a conflict, not an overwrite",async()=>{
    const local={id:localId,name:"Локальная версия",description:"",referenceImages:[]};
    const plan=await planner.planRestore({ownerId:owner,existingLocalItems:[local],fetchPage:async()=>page([row(cloudId,localId)])});
    assert.equal(plan.conflicts.length,1);
    assert.equal(plan.conflicts[0].reason,"local_and_cloud_content_differ");
  });
  await run("duplicate identity mappings across pages fail closed",async()=>{
    let call=0;
    await assert.rejects(()=>planner.planRestore({ownerId:owner,existingLocalItems:[],fetchPage:async()=>++call===1?page([row(cloudId,localId)],"next"):page([row("66666666-6666-4666-8666-666666666666",localId)])}));
  });

  await run("cloud identity already attached to a different local record becomes a conflict",async()=>{
    const otherLocalId="77777777-7777-4777-8777-777777777777";
    const local={id:otherLocalId,name:"Старая карточка",description:"",referenceImages:[],cloudBackup:{characterId:cloudId,version:1,referenceManifest:[]}};
    const plan=await planner.planRestore({ownerId:owner,existingLocalItems:[local],fetchPage:async()=>page([row(cloudId,localId)])});
    assert.equal(plan.proposedItems.length,0);
    assert.equal(plan.conflicts.length,1);
    assert.equal(plan.conflicts[0].reason,"cloud_character_already_mapped_to_another_local_id");
    assert.equal(plan.conflicts[0].localId,otherLocalId);
  });
  await run("duplicate cloud identities in the local library fail closed",async()=>{
    const one={id:localId,name:"A",cloudBackup:{characterId:cloudId}};
    const two={id:localId2,name:"B",cloudBackup:{characterId:cloudId}};
    await assert.rejects(()=>planner.planRestore({ownerId:owner,existingLocalItems:[one,two],fetchPage:async()=>page([])}),/duplicate cloud character mapping/);
  });
  await run("account switch during page fetch aborts plan",async()=>{
    let checks=0;
    await assert.rejects(()=>planner.planRestore({ownerId:owner,existingLocalItems:[],isCurrent:()=>++checks<2,fetchPage:async()=>page([row(cloudId,localId)])}),/Account changed/);
  });
  await run("validated restore plan commits atomically through owner-scoped adapter",async()=>{
    let stored=[];
    const plan=await planner.planRestore({ownerId:owner,existingLocalItems:[],fetchPage:async()=>page([row(cloudId,localId)])});
    const result=planner.applyRestorePlan({ownerId:owner,plan,readLocalItems:()=>stored,writeLocalItems:(writeOwner,items)=>{assert.equal(writeOwner,owner);stored=items;}});
    assert.deepEqual(result,{restoredCount:1,totalCount:1});
    assert.equal(stored[0].id,localId);
    assert.equal(stored[0].cloudBackup.characterId,cloudId);
    assert.deepEqual(stored[0].referenceImages,[]);
  });
  await run("restore commit refuses stale local state and performs no write",async()=>{
    let stored=[];
    const plan=await planner.planRestore({ownerId:owner,existingLocalItems:[],fetchPage:async()=>page([row(cloudId,localId)])});
    stored=[{id:localId2,name:"added elsewhere"}];
    let writes=0;
    assert.throws(()=>planner.applyRestorePlan({ownerId:owner,plan,readLocalItems:()=>stored,writeLocalItems:()=>writes++}),/changed after planning/);
    assert.equal(writes,0);
  });
  await run("failed restore read-back compensates to the original local library",async()=>{
    const original=[{id:localId2,name:"existing"}];
    let stored=original;
    let reads=0;
    const plan=await planner.planRestore({ownerId:owner,existingLocalItems:original,fetchPage:async()=>page([row(cloudId,localId)])});
    assert.throws(()=>planner.applyRestorePlan({
      ownerId:owner,plan,
      readLocalItems:()=>++reads===2?[{id:"tampered-readback"}]:stored,
      writeLocalItems:(writeOwner,items)=>{assert.equal(writeOwner,owner);stored=items;}
    }),/read-back verification failed/);
    assert.deepEqual(stored,original);
  });
  await run("writer failure after partial mutation attempts owner-scoped rollback",async()=>{
    const original=[{id:localId2,name:"existing"}];
    let stored=original;
    let writes=0;
    const plan=await planner.planRestore({ownerId:owner,existingLocalItems:original,fetchPage:async()=>page([row(cloudId,localId)])});
    assert.throws(()=>planner.applyRestorePlan({
      ownerId:owner,plan,
      readLocalItems:()=>stored,
      writeLocalItems:(writeOwner,items)=>{assert.equal(writeOwner,owner);writes++;stored=items;if(writes===1)throw new Error("simulated storage failure");}
    }),/simulated storage failure/);
    assert.equal(writes,2);
    assert.deepEqual(stored,original);
  });
  await run("restore commit refuses conflicts and account changes",async()=>{
    const conflictingLocal={id:localId,name:"Локальная версия",description:"",referenceImages:[]};
    const conflictPlan=await planner.planRestore({ownerId:owner,existingLocalItems:[conflictingLocal],fetchPage:async()=>page([row(cloudId,localId)])});
    const forgedPlan={complete:true,ownerId:owner,proposedItems:[],conflicts:[],baseLocalFingerprint:"[]"};
    let writes=0;
    assert.throws(()=>planner.applyRestorePlan({ownerId:owner,plan:conflictPlan,readLocalItems:()=>[conflictingLocal],writeLocalItems:()=>writes++}),/Resolve every/);
    assert.throws(()=>planner.applyRestorePlan({ownerId:owner,plan:forgedPlan,readLocalItems:()=>[],writeLocalItems:()=>writes++}),/completion proof/);
    const validPlan=await planner.planRestore({ownerId:owner,existingLocalItems:[],fetchPage:async()=>page([row(cloudId,localId)])});
    assert.throws(()=>planner.applyRestorePlan({ownerId:owner,plan:validPlan,readLocalItems:()=>[],writeLocalItems:()=>writes++,isCurrent:()=>false}),/Account changed/);
    assert.equal(writes,0);
  });
  await run("invalid passport kind and reference identity are rejected",async()=>{
    await assert.rejects(()=>planner.planRestore({ownerId:owner,existingLocalItems:[],fetchPage:async()=>page([row(cloudId,localId,{reference_data:{kind:"unknown",representation:"2d",passport:{},referenceImages:[]}})])}),/kind is invalid/);
    await assert.rejects(()=>planner.planRestore({ownerId:owner,existingLocalItems:[],fetchPage:async()=>page([row(cloudId,localId,{reference_data:{kind:"character",representation:"2d",passport:{},referenceImages:[{id:"",name:"x",type:"image/png"}]}})])}),/reference descriptor is invalid/);
  });
  await run("malformed passport field types are rejected",async()=>{
    const malformed=row(cloudId,localId,{reference_data:{kind:"character",representation:"2d",voice:17,passport:{face:0},referenceImages:[]}});
    await assert.rejects(()=>planner.planRestore({ownerId:owner,existingLocalItems:[],fetchPage:async()=>page([malformed])}),/Invalid character voice/);
  });
  await run("malformed cloud page is rejected without local mutation",async()=>{
    const local=[];
    await assert.rejects(()=>planner.planRestore({ownerId:owner,existingLocalItems:local,fetchPage:async()=>page([{...row(cloudId,localId),version:0}])}));
    assert.deepEqual(local,[]);
  });
})().catch(error=>{console.error(error);process.exitCode=1;});
