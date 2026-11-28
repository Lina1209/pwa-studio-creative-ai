const assert = require("node:assert/strict");
require("../character-cloud-restore.js");
const planner = globalThis.PWACharacterCloudRestore;
const owner = "11111111-1111-4111-8111-111111111111";
const cloudId = "22222222-2222-4222-8222-222222222222";
const localId = "33333333-3333-4333-8333-333333333333";
const localId2 = "44444444-4444-4444-8444-444444444444";
const referenceId = localId + "-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const referenceAsset = (overrides={}) => ({
  id:"99999999-9999-4999-8999-999999999999", character_id:cloudId,
  local_reference_id:referenceId, file_name:"front.png", file_type:"image/png",
  status:"ready", size_bytes:2048, content_sha256:"a".repeat(64), width:1024, height:768,
  ...overrides
});
const row = (id, sourceId, overrides={}) => ({
  id, source_local_id:sourceId, version:1, name:"Катти", description:"Описание",
  reference_data:{kind:"character",representation:"both",voice:"",passport:{face:"глаза",body:"силуэт",wardrobe:"худи",palette:"рыжий"},referenceImages:[]},
  created_at:"2026-11-28T00:00:00.000Z", ...overrides
});
const page = (items,next_cursor=null) => ({items,next_cursor});
const run = async (name, fn) => { await fn(); process.stdout.write("PASS "+name+"\n"); };
(async()=>{
  await run("fetches every page and produces local-ID-preserving metadata plan",async()=>{
    const calls=[];
    const withReference = row(cloudId,localId,{reference_data:{kind:"character",representation:"both",voice:"",passport:{face:"глаза",body:"силуэт",wardrobe:"худи",palette:"рыжий"},referenceImages:[{id:referenceId,name:"front.png",type:"image/png"}]}});
    const pages=[page([withReference],"cursor-1"),page([row("55555555-5555-4555-8555-555555555555",localId2)])];
    const plan=await planner.planRestore({ownerId:owner,existingLocalItems:[],fetchPage:async cursor=>{calls.push(cursor);return pages[calls.length-1];},fetchReferences:async ids=>{assert.deepEqual(ids,[cloudId]);return [referenceAsset()];}});
    assert.deepEqual(calls,[null,"cursor-1"]);
    assert.equal(plan.complete,true);
    assert.equal(plan.pagesRead,2);
    assert.equal(plan.cloudCount,2);
    assert.equal(plan.proposedItems.length,2);
    assert.equal(plan.proposedItems[0].id,localId);
    assert.equal(plan.proposedItems[0].cloudBackup.characterId,cloudId);
    assert.deepEqual(plan.proposedItems[0].referenceImages,[]);
    assert.equal(plan.proposedItems[0].cloudBackup.referenceManifest[0].name,"front.png");
    assert.equal(plan.proposedItems[0].cloudBackup.referenceManifest[0].cloudAssetId,referenceAsset().id);
    assert.equal(plan.proposedItems[0].cloudBackup.referenceManifest[0].expectedSha256,"a".repeat(64));
    assert.equal(plan.proposedItems[0].cloudBackup.referenceManifest[0].expectedSizeBytes,2048);
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
    const manifest=[{id:referenceId,name:"front.png",type:"image/png"}];
    const local={id:localId,name:"Катти",description:"Описание",kind:"character",representation:"both",voice:"",passport:{face:"глаза",body:"силуэт",wardrobe:"худи",palette:"рыжий"},referenceImages:[],cloudBackup:{characterId:cloudId,version:1,referenceManifest:manifest}};
    const cloudRow=row(cloudId,localId,{reference_data:{kind:"character",representation:"both",voice:"",passport:local.passport,referenceImages:manifest}});
    const plan=await planner.planRestore({ownerId:owner,existingLocalItems:[local],fetchPage:async()=>page([cloudRow]),fetchReferences:async()=>[referenceAsset()]});
    assert.equal(plan.unchanged.length,1);
    assert.equal(plan.conflicts.length,0);
  });


  await run("reference descriptors require explicit ready media mappings",async()=>{
    const cloudRow=row(cloudId,localId,{reference_data:{kind:"character",representation:"both",voice:"",passport:{},referenceImages:[{id:referenceId,name:"front.png",type:"image/png"}]}});
    await assert.rejects(()=>planner.planRestore({ownerId:owner,existingLocalItems:[],fetchPage:async()=>page([cloudRow])}),/loader is required/);
    await assert.rejects(()=>planner.planRestore({ownerId:owner,existingLocalItems:[],fetchPage:async()=>page([cloudRow]),fetchReferences:async()=>[]}),/no explicit media asset mapping/);
  });
  await run("reference restore rejects pending assets and integrity mismatches",async()=>{
    const cloudRow=row(cloudId,localId,{reference_data:{kind:"character",representation:"both",voice:"",passport:{},referenceImages:[{id:referenceId,name:"front.png",type:"image/png"}]}});
    await assert.rejects(()=>planner.planRestore({ownerId:owner,existingLocalItems:[],fetchPage:async()=>page([cloudRow]),fetchReferences:async()=>[referenceAsset({status:"object_uploaded"})]}),/not ready/);
    await assert.rejects(()=>planner.planRestore({ownerId:owner,existingLocalItems:[],fetchPage:async()=>page([cloudRow]),fetchReferences:async()=>[referenceAsset({content_sha256:"bad"})]}),/integrity metadata/);
  });
  await run("reference restore rejects duplicate asset-to-reference mappings",async()=>{
    const cloudRow=row(cloudId,localId,{reference_data:{kind:"character",representation:"both",voice:"",passport:{},referenceImages:[{id:referenceId,name:"front.png",type:"image/png"}]}});
    await assert.rejects(()=>planner.planRestore({ownerId:owner,existingLocalItems:[],fetchPage:async()=>page([cloudRow]),fetchReferences:async()=>[referenceAsset(),referenceAsset({id:"88888888-8888-4888-8888-888888888888"})]}),/duplicate local reference mappings/);
  });

  await run("v2 manifest keeps logical slot stable and resolves the immutable asset identity",async()=>{
    const slotId=localId2;
    const cloudRow=row(cloudId,localId,{reference_data:{kind:"character",representation:"both",voice:"",passport:{},referenceImages:[{slot_id:slotId,asset_local_reference_id:referenceId,name:"front.png",type:"image/png"}]}});
    const plan=await planner.planRestore({ownerId:owner,existingLocalItems:[],fetchPage:async()=>page([cloudRow]),fetchReferences:async()=>[referenceAsset()]});
    const manifest=plan.proposedItems[0].cloudBackup.referenceManifest[0];
    assert.equal(manifest.id,slotId);
    assert.equal(manifest.slotId,slotId);
    assert.equal(manifest.assetLocalReferenceId,referenceId);
    assert.equal(manifest.localReferenceId,referenceId);
    assert.equal(manifest.cloudAssetId,referenceAsset().id);
  });
  await run("v2 manifest local comparison accepts stable slot plus immutable asset identity",async()=>{
    const slotId=localId2;
    const v2=[{slot_id:slotId,asset_local_reference_id:referenceId,name:"front.png",type:"image/png"}];
    const local={id:localId,name:"Катти",description:"Описание",kind:"character",representation:"both",voice:"",passport:{face:"глаза",body:"силуэт",wardrobe:"худи",palette:"рыжий"},referenceImages:v2,cloudBackup:{characterId:cloudId}};
    const cloudRow=row(cloudId,localId,{reference_data:{kind:"character",representation:"both",voice:"",passport:local.passport,referenceImages:v2}});
    const plan=await planner.planRestore({ownerId:owner,existingLocalItems:[local],fetchPage:async()=>page([cloudRow]),fetchReferences:async()=>[referenceAsset()]});
    assert.equal(plan.unchanged.length,1);
    assert.equal(plan.conflicts.length,0);
  });
  await run("v2 manifest rejects duplicate logical slots and ambiguous mixed identity fields",async()=>{
    const cloudRow=row(cloudId,localId,{reference_data:{kind:"character",representation:"both",voice:"",passport:{},referenceImages:[
      {slot_id:localId2,asset_local_reference_id:referenceId,name:"front.png",type:"image/png"},
      {slot_id:localId2,asset_local_reference_id:localId+"-bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",name:"side.png",type:"image/png"}
    ]}});
    await assert.rejects(()=>planner.planRestore({ownerId:owner,existingLocalItems:[],fetchPage:async()=>page([cloudRow]),fetchReferences:async()=>[]}),/duplicate identities/);
    const mixed=row(cloudId,localId,{reference_data:{kind:"character",representation:"both",voice:"",passport:{},referenceImages:[{id:referenceId,slot_id:localId2,asset_local_reference_id:referenceId,name:"front.png",type:"image/png"}]}});
    await assert.rejects(()=>planner.planRestore({ownerId:owner,existingLocalItems:[],fetchPage:async()=>page([mixed]),fetchReferences:async()=>[]}),/v2 identity is invalid/);
  });
  await run("matching passport without a persisted cloud identity binding requires conflict resolution",async()=>{
    const local={id:localId,name:"Катти",description:"Описание",kind:"character",representation:"both",voice:"",passport:{face:"глаза",body:"силуэт",wardrobe:"худи",palette:"рыжий"},referenceImages:[]};
    const plan=await planner.planRestore({ownerId:owner,existingLocalItems:[local],fetchPage:async()=>page([row(cloudId,localId)])});
    assert.equal(plan.unchanged.length,0);
    assert.equal(plan.proposedItems.length,0);
    assert.equal(plan.conflicts.length,1);
    assert.equal(plan.conflicts[0].reason,"local_record_missing_cloud_identity_binding");
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
    assert.equal(plan.conflicts[0].reason,"local_record_missing_cloud_identity_binding");
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
  await run("selection creates an issued subset plan without mutating the full preview",async()=>{
    const secondCloud="55555555-5555-4555-8555-555555555555";
    const secondLocal="66666666-6666-4666-8666-666666666666";
    const plan=await planner.planRestore({ownerId:owner,existingLocalItems:[],fetchPage:async()=>page([row(cloudId,localId),row(secondCloud,secondLocal)])});
    const selected=planner.selectRestorePlan({ownerId:owner,plan,selectedCloudIds:[secondCloud]});
    assert.equal(selected.cloudCount,1);
    assert.deepEqual(selected.selectedCloudIds,[secondCloud]);
    assert.equal(selected.proposedItems.length,1);
    assert.equal(selected.proposedItems[0].cloudBackup.characterId,secondCloud);
    assert.equal(plan.proposedItems.length,2);
    assert.throws(()=>planner.applyRestorePlan({ownerId:owner,plan:{...selected},readLocalItems:()=>[],writeLocalItems:()=>{}}),/completion proof/);
    assert.throws(()=>planner.selectRestorePlan({ownerId:owner,plan,selectedCloudIds:[secondCloud,secondCloud]}),/duplicate/);
    assert.throws(()=>planner.selectRestorePlan({ownerId:owner,plan,selectedCloudIds:["77777777-7777-4777-8777-777777777777"]}),/outside/);
  });
  await run("selected restore preview summarizes safe actions, conflicts and pending images without side effects",async()=>{
    const conflictCloud="55555555-5555-4555-8555-555555555555";
    const conflictLocal="66666666-6666-4666-8666-666666666666";
    const conflictRecord={id:conflictLocal,name:"Локальная Катти",description:"локально",referenceImages:[]};
    const cloudWithImage=row(cloudId,localId,{reference_data:{kind:"character",representation:"both",voice:"",passport:{},referenceImages:[{id:referenceId,name:"front.png",type:"image/png"}]}});
    const conflictRow=row(conflictCloud,conflictLocal);
    const plan=await planner.planRestore({
      ownerId:owner,existingLocalItems:[conflictRecord],
      fetchPage:async()=>page([cloudWithImage,conflictRow]),
      fetchReferences:async ids=>{assert.deepEqual(ids,[cloudId]);return [referenceAsset()];}
    });
    const selected=planner.selectRestorePlan({ownerId:owner,plan,selectedCloudIds:[cloudId,conflictCloud]});
    const preview=planner.buildRestorePreview({ownerId:owner,plan:selected});
    assert.equal(preview.selectedCount,2);
    assert.equal(preview.restorableCount,1);
    assert.equal(preview.conflictCount,1);
    assert.equal(preview.unchangedCount,0);
    assert.equal(preview.referenceCount,1);
    assert.equal(preview.canContinue,false);
    assert.equal(preview.requiresExplicitConfirmation,true);
    assert.equal(preview.writesPerformed,false);
    assert.equal(preview.downloadsPerformed,false);
    assert.equal(preview.items[0].status,"ready_to_stage");
    assert.equal(preview.items[0].referenceStatusLabel,"Изображения проверены по облачному каталогу; загрузка ещё не выполнена.");
    assert.equal(preview.items[1].status,"conflict");
    assert.match(preview.items[1].conflictMessage,/локальной и облачной карточек/);
    assert.equal(Object.isFrozen(preview),true);
    assert.equal(Object.isFrozen(preview.items[0]),true);
    assert.equal(plan.proposedItems.length,1);
    assert.equal(conflictRecord.name,"Локальная Катти");
    assert.throws(()=>planner.buildRestorePreview({ownerId:owner,plan:{...selected}}),/issued complete plan/);
    assert.throws(()=>planner.buildRestorePreview({ownerId:localId,plan:selected}),/issued complete plan/);
  });
  await run("restore preview reports already-current cards and empty image manifests",async()=>{
    const local={id:localId,name:"Катти",description:"Описание",kind:"character",representation:"both",voice:"",passport:{face:"глаза",body:"силуэт",wardrobe:"худи",palette:"рыжий"},referenceImages:[],cloudBackup:{characterId:cloudId}};
    const cloudRow=row(cloudId,localId,{reference_data:{kind:"character",representation:"both",voice:"",passport:local.passport,referenceImages:[]}});
    const plan=await planner.planRestore({ownerId:owner,existingLocalItems:[local],fetchPage:async()=>page([cloudRow])});
    const preview=planner.buildRestorePreview({ownerId:owner,plan});
    assert.equal(preview.unchangedCount,1);
    assert.equal(preview.restorableCount,0);
    assert.equal(preview.conflictCount,0);
    assert.equal(preview.canContinue,false);
    assert.equal(preview.requiresExplicitConfirmation,false);
    assert.equal(preview.items[0].statusLabel,"Уже актуальна");
    assert.equal(preview.items[0].referenceStatusLabel,"Изображений для восстановления нет.");
  });
  await run("explicit restore confirmation is bound to the exact owner, selection and preview",async()=>{
    const plan=await planner.planRestore({ownerId:owner,existingLocalItems:[],fetchPage:async()=>page([row(cloudId,localId)])});
    const preview=planner.buildRestorePreview({ownerId:owner,plan});
    assert.throws(()=>planner.confirmRestorePreview({ownerId:owner,plan,preview,confirmed:false}),/Explicit user confirmation/);
    const confirmation=planner.confirmRestorePreview({ownerId:owner,plan,preview,confirmed:true});
    assert.equal(confirmation.ownerId,owner);
    assert.deepEqual(confirmation.selectedCloudIds,[cloudId]);
    assert.equal(confirmation.selectedCount,1);
    assert.equal(confirmation.restorableCount,1);
    assert.equal(planner.validateRestoreConfirmation({ownerId:owner,plan,preview,confirmation}),true);
    assert.equal(planner.validateRestoreConfirmation({ownerId:localId,plan,preview,confirmation}),false);
    assert.equal(planner.validateRestoreConfirmation({ownerId:owner,plan,preview:{...preview},confirmation}),false);
    assert.equal(planner.validateRestoreConfirmation({ownerId:owner,plan:{...plan},preview,confirmation}),false);
    assert.throws(()=>planner.confirmRestorePreview({ownerId:owner,plan,preview:{...preview},confirmed:true}),/exact reviewed preview/);
  });
  await run("restore confirmation tokens expire when planner module is reloaded",async()=>{
    const plan=await planner.planRestore({ownerId:owner,existingLocalItems:[],fetchPage:async()=>page([row(cloudId,localId)])});
    const preview=planner.buildRestorePreview({ownerId:owner,plan});
    const confirmation=planner.confirmRestorePreview({ownerId:owner,plan,preview,confirmed:true});
    assert.equal(planner.validateRestoreConfirmation({ownerId:owner,plan,preview,confirmation}),true);
    const modulePath=require.resolve("../character-cloud-restore.js");
    delete require.cache[modulePath];
    require("../character-cloud-restore.js");
    const reloaded=globalThis.PWACharacterCloudRestore;
    assert.equal(reloaded.validateRestoreConfirmation({ownerId:owner,plan,preview,confirmation}),false);
    const freshPlan=await reloaded.planRestore({ownerId:owner,existingLocalItems:[],fetchPage:async()=>page([row(cloudId,localId)])});
    const freshPreview=reloaded.buildRestorePreview({ownerId:owner,plan:freshPlan});
    assert.equal(reloaded.validateRestoreConfirmation({ownerId:owner,plan:freshPlan,preview:freshPreview,confirmation}),false);
  });
  await run("restore confirmation is blocked when preview contains conflicts or no restorable cards",async()=>{
    const conflictLocal={id:localId,name:"Local",description:"",referenceImages:[]};
    const conflictPlan=await planner.planRestore({ownerId:owner,existingLocalItems:[conflictLocal],fetchPage:async()=>page([row(cloudId,localId)])});
    const conflictPreview=planner.buildRestorePreview({ownerId:owner,plan:conflictPlan});
    assert.throws(()=>planner.confirmRestorePreview({ownerId:owner,plan:conflictPlan,preview:conflictPreview,confirmed:true}),/Resolve restore conflicts/);
    const unchanged={id:localId,name:"Катти",description:"Описание",kind:"character",representation:"both",voice:"",passport:{face:"глаза",body:"силуэт",wardrobe:"худи",palette:"рыжий"},referenceImages:[],cloudBackup:{characterId:cloudId}};
    const unchangedPlan=await planner.planRestore({ownerId:owner,existingLocalItems:[unchanged],fetchPage:async()=>page([row(cloudId,localId,{reference_data:{kind:"character",representation:"both",voice:"",passport:unchanged.passport,referenceImages:[]}})])});
    const unchangedPreview=planner.buildRestorePreview({ownerId:owner,plan:unchangedPlan});
    assert.throws(()=>planner.confirmRestorePreview({ownerId:owner,plan:unchangedPlan,preview:unchangedPreview,confirmed:true}),/at least one restorable character/);
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
  await run("backup serializer preserves a v2 slot and immutable asset identity",async()=>{
    const slotId=localId2;
    const manifest=planner.serializeReferenceManifest([], [{id:slotId,slotId,assetLocalReferenceId:referenceId,name:"front.png",type:"image/png"}]);
    assert.deepEqual(manifest,[{slot_id:slotId,asset_local_reference_id:referenceId,name:"front.png",type:"image/png"}]);
  });
  await run("backup serializer keeps legacy reference shape when identities are equal",async()=>{
    assert.deepEqual(planner.serializeReferenceManifest([{id:referenceId,name:"front.png",type:"image/png"}],[]),[{id:referenceId,name:"front.png",type:"image/png"}]);
  });
  await run("local legacy card does not erase cloud v2 asset binding",async()=>{
    const merged=planner.serializeReferenceManifest([{id:localId2,name:"local name",type:"image/jpeg"}],[{id:localId2,slotId:localId2,assetLocalReferenceId:referenceId,name:"cloud name",type:"image/png"}]);
    assert.deepEqual(merged,[{slot_id:localId2,asset_local_reference_id:referenceId,name:"local name",type:"image/jpeg"}]);
  });
  await run("explicit local v2 replacement updates only the immutable asset identity",async()=>{
    const nextAsset=localId;
    const merged=planner.serializeReferenceManifest([{id:localId2,slotId:localId2,assetLocalReferenceId:nextAsset,name:"new.png",type:"image/png"}],[{id:localId2,slotId:localId2,assetLocalReferenceId:referenceId,name:"old.png",type:"image/jpeg"}]);
    assert.deepEqual(merged,[{slot_id:localId2,asset_local_reference_id:nextAsset,name:"new.png",type:"image/png"}]);
  });
  await run("backup serializer rejects duplicate immutable asset bindings",async()=>{
    assert.throws(()=>planner.serializeReferenceManifest([{id:localId2,slotId:localId2,assetLocalReferenceId:referenceId},{id:localId,slotId:localId,assetLocalReferenceId:referenceId}],[]),/duplicate asset identities/);
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
