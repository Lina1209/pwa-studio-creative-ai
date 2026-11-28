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
  await run("account switch during page fetch aborts plan",async()=>{
    let checks=0;
    await assert.rejects(()=>planner.planRestore({ownerId:owner,existingLocalItems:[],isCurrent:()=>++checks<2,fetchPage:async()=>page([row(cloudId,localId)])}),/Account changed/);
  });
  await run("malformed cloud page is rejected without local mutation",async()=>{
    const local=[];
    await assert.rejects(()=>planner.planRestore({ownerId:owner,existingLocalItems:local,fetchPage:async()=>page([{...row(cloudId,localId),version:0}])}));
    assert.deepEqual(local,[]);
  });
})().catch(error=>{console.error(error);process.exitCode=1;});
