/* Crash-aware activation of fully staged Character Library restores.
 * All dependencies are injected. No UI wiring, network, cloud mutation, or cleanup.
 */
(() => {
 "use strict";
 const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
 const MIME=new Set(["image/png","image/jpeg","image/webp"]);
 const fail=m=>{throw new Error(m);};
 const canonical=v=>JSON.stringify(v,(k,x)=>x&&typeof x==="object"&&!Array.isArray(x)?Object.keys(x).sort().reduce((o,n)=>(o[n]=x[n],o),{}):x);
 const hex=b=>Array.from(new Uint8Array(b),x=>x.toString(16).padStart(2,"0")).join("");
 const digest=async v=>hex(await crypto.subtle.digest("SHA-256",typeof v==="string"?new TextEncoder().encode(v):await v.arrayBuffer()));
 const uuid=(v)=>typeof v==="string"&&UUID.test(v);
 const same=(a,b)=>canonical(a)===canonical(b);
 function dependencies(input){
  const {journal,blobStore,localAdapter,inspectImage,isCurrent=()=>true}=input||{};
  if(!journal||!blobStore||!localAdapter||typeof inspectImage!=="function"||typeof isCurrent!=="function")fail("Activation adapters are incomplete.");
  for(const name of ["get","acquireLease","renewLease","checkpoint","releaseLease"])if(typeof journal[name]!=="function")fail("Restore journal adapter is incomplete.");
  if(typeof blobStore.readStagedBlob!=="function"||typeof localAdapter.readLocalItems!=="function"||typeof localAdapter.writeLocalItems!=="function")fail("Owner-scoped storage adapters are incomplete.");
  return {journal,blobStore,localAdapter,inspectImage,isCurrent};
 }
 function assertCurrent(isCurrent){if(!isCurrent())fail("Account changed during restore activation.");}
 function manifestMap(plan){
  if(!Array.isArray(plan.proposedItems))fail("Fresh restore plan is missing proposed cards.");
  const out=new Map();
  for(const card of plan.proposedItems){
   if(!card||!uuid(card.id)||!card.cloudBackup||!uuid(card.cloudBackup.characterId)||!Array.isArray(card.cloudBackup.referenceManifest))fail("Restore plan contains an invalid card.");
   if(out.has(card.cloudBackup.characterId))fail("Restore plan repeats a cloud character.");
   out.set(card.cloudBackup.characterId,card);
  }
  return out;
 }
 function validateJournalReferences(row,plan){
  if(row.state!=="ready_to_activate")fail("Restore operation is not ready for activation.");
  if(row.references.some(x=>x.state!=="verified_staged"))fail("Every media reference must be verified before activation.");
  const cards=manifestMap(plan),seen=new Set();
  if(cards.size!==row.selectedCharacterIds.length)fail("Fresh plan does not match the selected cloud character set.");
  for(const id of row.selectedCharacterIds)if(!cards.has(id))fail("Fresh plan is missing a selected cloud character.");
  for(const ref of row.references){
   const card=cards.get(ref.characterId);
   if(!card||card.id!==ref.sourceLocalId)fail("Staged reference is bound to a different character card.");
   const item=card.cloudBackup.referenceManifest.find(x=>x.cloudAssetId===ref.cloudAssetId);
   if(!item||item.characterId!==ref.characterId||item.sourceLocalId!==ref.sourceLocalId||
      item.localReferenceId!==ref.localReferenceId||item.expectedSha256!==ref.expectedSha256||
      item.expectedSizeBytes!==ref.expectedSizeBytes||item.expectedMimeType!==ref.expectedMimeType||
      item.width!==ref.width||item.height!==ref.height||item.name!==ref.name)fail("Staged reference does not match the fresh cloud manifest.");
   const key=ref.characterId+":"+ref.localReferenceId;
   if(seen.has(key))fail("Duplicate staged local-reference mapping.");
   seen.add(key);
  }
  let expected=0;
  for(const card of plan.proposedItems)expected+=card.cloudBackup.referenceManifest.length;
  if(expected!==row.references.length)fail("Not every cloud reference has a verified staged Blob.");
 }
 function createReferenceImages(card,row){
  return row.references.filter(x=>x.characterId===card.cloudBackup.characterId)
   .map(x=>({id:x.localStagedBlobId,name:x.name,type:x.type,sourceReferenceId:x.localReferenceId}));
 }
 async function inspectAndVerify(ref,blob,inspectImage){
  if(!(blob instanceof Blob)||blob.size!==ref.expectedSizeBytes||blob.type!==ref.expectedMimeType)fail("Staged image size or MIME type changed.");
  if(!MIME.has(blob.type))fail("Staged image MIME type is unsupported.");
  const actual=await digest(blob);
  if(actual!==ref.expectedSha256.toLowerCase())fail("Staged image SHA-256 verification failed.");
  const dimensions=await inspectImage(blob);
  if(!dimensions||dimensions.width!==ref.width||dimensions.height!==ref.height)fail("Staged image dimensions verification failed.");
 }
 async function prepareMerged({ownerId,operationId,row,plan,localAdapter,blobStore,inspectImage,isCurrent}){
  if(!plan||plan.complete!==true||plan.ownerId!==ownerId||!Array.isArray(plan.conflicts)||plan.conflicts.length)fail("A fresh, conflict-free restore plan is required.");
  if(!Array.isArray(plan.proposedItems)||!plan.baseLocalFingerprint)fail("Fresh restore plan is incomplete.");
  const baseDigest=await digest(plan.baseLocalFingerprint);
  if(baseDigest!==row.localBaseFingerprint)fail("Local base snapshot differs from the durable restore checkpoint.");
  const current=localAdapter.readLocalItems(ownerId);
  if(current&&typeof current.then==="function")fail("Local metadata adapter must be synchronous.");
  if(canonical(current)!==plan.baseLocalFingerprint)fail("Local library changed; rebuild the restore plan.");
  validateJournalReferences(row,plan);
  const existingIds=new Set(current.map(x=>x?.id));
  const cloudIds=new Set(current.map(x=>x?.cloudBackup?.characterId).filter(Boolean));
  const additions=[];
  for(const card of plan.proposedItems){
   if(existingIds.has(card.id)||cloudIds.has(card.cloudBackup.characterId))fail("Restore would overwrite or duplicate an existing local identity.");
   existingIds.add(card.id);cloudIds.add(card.cloudBackup.characterId);
   const refs=row.references.filter(x=>x.characterId===card.cloudBackup.characterId);
   const hydrated={...card,referenceImages:createReferenceImages(card,row),restoreOperationId:operationId};
   // Re-read and re-hash each Blob immediately before metadata activation.
   for(const ref of refs){
    assertCurrent(isCurrent);
    const blob=await blobStore.readStagedBlob({ownerId,operationId,cloudAssetId:ref.cloudAssetId,localStagedBlobId:ref.localStagedBlobId});
    assertCurrent(isCurrent);
    await inspectAndVerify(ref,blob,inspectImage);
   }
   additions.push(hydrated);
  }
  const merged=[...additions,...current];
  if(merged.length>100)fail("Local library limit of 100 materials would be exceeded.");
  return {current,merged,baseDigest,mergedDigest:await digest(canonical(merged))};
 }
 async function activateRestore(input){
  const {journal,blobStore,localAdapter,inspectImage,isCurrent}=dependencies(input);
  const {ownerId,operationId,plan,expectedRevision}=input;
  if(!uuid(ownerId)||!uuid(operationId))fail("Invalid restore owner or operation identity.");
  assertCurrent(isCurrent);
  let lease=null,heartbeat=null,renewal=Promise.resolve(),row=null,revision=expectedRevision,writeAttempted=false;
  try{
   row=await journal.get(ownerId,operationId);
   if(!row||row.revision!==expectedRevision||row.state!=="ready_to_activate")fail("Restore checkpoint changed; refresh and re-plan.");
   lease=await journal.acquireLease(ownerId,operationId,{ttlMs:30000});
   row=await journal.get(ownerId,operationId);
   if(!row||row.state!=="ready_to_activate"||row.revision!==expectedRevision+1||row.leaseEpoch!==lease.epoch)fail("Activation lease or checkpoint changed.");
   revision=row.revision;
   let lost=false;
   const renew=async()=>{try{lease=await journal.renewLease(ownerId,operationId,lease,{ttlMs:30000});}catch{lost=true;}};
   heartbeat=setInterval(()=>{renewal=renewal.then(renew);},10000);
   const assertLease=()=>{assertCurrent(isCurrent);if(lost||!lease||Date.parse(lease.expiresAt)<=Date.now())fail("Activation lease expired or was fenced.");};
   const prepared=await prepareMerged({ownerId,operationId,row,plan,localAdapter,blobStore,inspectImage,isCurrent});
   assertLease();
   const intent={baseDigest:prepared.baseDigest,mergedDigest:prepared.mergedDigest,intendedCount:prepared.merged.length,operationMarker:operationId,preparedAt:new Date().toISOString()};
   const activating=await journal.checkpoint({ownerId,operationId,leaseToken:lease.token,leaseEpoch:lease.epoch,expectedRevision:revision,state:"activating",activation:intent});
   revision=activating.revision;
   await renewal;assertLease();
   // Single synchronous owner-scoped metadata-key replacement is the commit point.
   writeAttempted=true;
   const result=localAdapter.writeLocalItems(ownerId,prepared.merged);
   if(result&&typeof result.then==="function")fail("Local metadata activation must be synchronous.");
   const readBack=localAdapter.readLocalItems(ownerId);
   if(readBack&&typeof readBack.then==="function")fail("Local metadata read-back must be synchronous.");
   if(!Array.isArray(readBack)||await digest(canonical(readBack))!==intent.mergedDigest)fail("Activated metadata read-back digest does not match.");
   if(readBack.filter(x=>x?.restoreOperationId===operationId).length!==intent.intendedCount-prepared.current.length)fail("Activated card markers do not match the intended restore count.");
   await renewal;assertLease();
   const committed=await journal.checkpoint({ownerId,operationId,leaseToken:lease.token,leaseEpoch:lease.epoch,expectedRevision:revision,state:"committed"});
   revision=committed.revision;
   return Object.freeze({state:"committed",restoredCount:plan.proposedItems.length,totalCount:readBack.length,mergedDigest:intent.mergedDigest});
  }catch(error){
   if(row&&lease&&isCurrent()){
    try{
     const latest=await journal.get(ownerId,operationId);
     if(latest&&latest.state==="activating"&&latest.lease?.token===lease.token&&latest.lease.epoch===lease.epoch){
      const actual=localAdapter.readLocalItems(ownerId);
      const actualDigest=await digest(canonical(actual));
      const state=writeAttempted&&actualDigest!==(latest.activation?.baseDigest)?"activation_uncertain":"paused_retryable";
      await journal.checkpoint({ownerId,operationId,leaseToken:lease.token,leaseEpoch:lease.epoch,expectedRevision:latest.revision,state});
     }
    }catch{/* Preserve original failure; the persisted activation intent remains recoverable. */}
   }
   throw error;
  }finally{
   if(heartbeat)clearInterval(heartbeat);
   await renewal;
   if(lease)try{await journal.releaseLease(ownerId,operationId,lease);}catch{/* lease expiry/takeover is fenced */}
  }
 }
 async function recoverActivation(input){
  const {journal,localAdapter,isCurrent}=dependencies({...input,blobStore:input.blobStore||{readStagedBlob:async()=>null},inspectImage:input.inspectImage||(()=>({width:1,height:1}))});
  const {ownerId,operationId,expectedRevision}=input;
  assertCurrent(isCurrent);
  const row=await journal.get(ownerId,operationId);
  if(!row||row.revision!==expectedRevision||!["activating","activation_uncertain","paused_retryable"].includes(row.state)||!row.activation)fail("No recoverable activation intent exists.");
  const lease=await journal.acquireLease(ownerId,operationId,{ttlMs:30000});
  try{
   const current=await journal.get(ownerId,operationId);
   if(!current||current.revision!==expectedRevision+1||current.leaseEpoch!==lease.epoch)fail("Recovery checkpoint changed.");
   const items=localAdapter.readLocalItems(ownerId);
   if(items&&typeof items.then==="function")fail("Local metadata adapter must be synchronous.");
   const actual=await digest(canonical(items));
   let next;
   if(actual===current.activation.mergedDigest&&items.filter(x=>x?.restoreOperationId===operationId).length===current.activation.intendedCount-(current.activation.intendedCount-items.filter(x=>x?.restoreOperationId===operationId).length)){
     next="committed";
    }else if(actual===current.activation.baseDigest){
     next="paused_retryable";
    }else next="conflict";
   const saved=await journal.checkpoint({ownerId,operationId,leaseToken:lease.token,leaseEpoch:lease.epoch,expectedRevision:current.revision,state:next});
   return Object.freeze({state:saved.state,reason:next==="committed"?"merged_digest_matches":next==="paused_retryable"?"base_digest_matches":"metadata_matches_neither_safe_boundary"});
  }finally{try{await journal.releaseLease(ownerId,operationId,lease);}catch{}}
 }
 globalThis.PWACharacterRestoreActivation=Object.freeze({activateRestore,recoverActivation});
})();