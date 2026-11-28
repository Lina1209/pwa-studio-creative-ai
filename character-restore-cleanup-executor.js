/* Explicit, dependency-injected staged-Blob cleanup executor.
 * Not wired to the app, UI, worker, scheduler, or production. Tests must use disposable stores.
 * Deletes only one exact, previously reconciled restore-stage key after a fresh full recheck.
 */
(() => {
  "use strict";
  const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const SHA=/^[a-f0-9]{64}$/i,MAX_PAGES=100,MAX_ROWS=10000,MAX_CANDIDATES=600;
  const fail=m=>{throw new Error(m)};
  const validUuid=v=>typeof v==="string"&&UUID.test(v);
  const canonical=v=>{if(Array.isArray(v))return "["+v.map(canonical).join(",")+"]";if(v&&typeof v==="object")return "{"+Object.keys(v).sort().map(k=>JSON.stringify(k)+":"+canonical(v[k])).join(",")+"}";return JSON.stringify(v);};
  const digest=async value=>{const h=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(canonical(value)));return Array.from(new Uint8Array(h),x=>x.toString(16).padStart(2,"0")).join("");};
  async function collectAll(adapter,ownerId,label){
    const rows=[];let cursor=null,pages=0;
    do{
      const page=await adapter.listPage(ownerId,{limit:100,cursor});
      if(!page||!Array.isArray(page.items)||page.items.length>100)fail(label+" page is malformed.");
      rows.push(...page.items);
      if(rows.length>MAX_ROWS)fail(label+" inventory exceeds the safety bound.");
      cursor=page.nextCursor;
      if(cursor!==null&&(typeof cursor!=="string"||!cursor.length||cursor.length>2048))fail(label+" cursor is invalid.");
      if(++pages>MAX_PAGES)fail(label+" pagination did not terminate within the safety bound.");
    }while(cursor!==null);
    return rows;
  }
  function referencesIn(cards){
    if(!Array.isArray(cards)||cards.length>100)fail("Owner metadata inventory is incomplete.");
    const ids=new Set();
    for(const card of cards){
      if(!card||typeof card!=="object"||(card.referenceImages!=null&&!Array.isArray(card.referenceImages)))fail("Owner metadata contains malformed cards.");
      for(const ref of card.referenceImages||[]){
        if(!ref||typeof ref.id!=="string"||!ref.id.trim())fail("Owner metadata contains an invalid reference identity.");
        ids.add(ref.id);
      }
    }
    return ids;
  }
  function assertInventories(ownerId,operations,candidate,activeIds){
    const op=operations.find(x=>x?.operationId===candidate.operationId);
    if(!op||op.ownerId!==ownerId||op.state!=="aborted"||op.revision!==candidate.operationRevision||
       (op.lease&&Date.parse(op.lease.expiresAt)>Date.now()))fail("Source restore operation is not terminal and unchanged.");
    if(!Array.isArray(op.references)||op.references.length>600)fail("Source reference inventory is incomplete.");
    const matches=op.references.filter(r=>r?.localStagedBlobId===candidate.localStagedBlobId&&r?.cloudAssetId===candidate.cloudAssetId&&r.state==="verified_staged");
    if(matches.length!==1||activeIds.has(candidate.localStagedBlobId))fail("Candidate is referenced or its source mapping changed.");
    let blobMatches=0,assetMatches=0;
    for(const other of operations)for(const ref of other.references||[]){
      if(ref.localStagedBlobId===candidate.localStagedBlobId)blobMatches++;
      if(ref.cloudAssetId===candidate.cloudAssetId&&other.operationId!==candidate.operationId)assetMatches++;
    }
    if(blobMatches!==1||assetMatches!==0)fail("Another restore operation may still own this staged asset.");
    const ref=matches[0];
    if(ref.expectedSha256!==candidate.sha256||ref.expectedSizeBytes!==candidate.sizeBytes||
       ref.expectedMimeType!==candidate.mimeType||ref.width!==candidate.width||ref.height!==candidate.height)
      fail("Durable source proof differs from the cleanup manifest.");
    return {operation:op,reference:ref};
  }
  async function executeEligibleCleanup(input){
    const {ownerId,cleanupId,restoreJournal,cleanupJournal,blobStore,localAdapter,
      ownerLock=globalThis.PWACharacterOwnerCoordinationLock,inspectImage,isCurrent=()=>true,
      now=()=>Date.now(),maxDeletes=1}=input||{};
    if(!validUuid(ownerId)||!validUuid(cleanupId)||!restoreJournal||!cleanupJournal||!blobStore||!localAdapter||!ownerLock||
       typeof inspectImage!=="function"||typeof isCurrent!=="function"||!Number.isInteger(maxDeletes)||maxDeletes<1||maxDeletes>10)
      fail("Cleanup executor adapters or bounds are invalid.");
    for(const [obj,methods,label] of [
      [restoreJournal,["listPage"],"Restore journal"],[cleanupJournal,["listPage","getManifest","beginCandidateDelete","finalizeCandidateDeleted"],"Cleanup journal"],
      [blobStore,["readStagedBlob","deleteStagedBlob"],"Blob store"],[localAdapter,["readLocalItems"],"Local metadata"]
    ])for(const method of methods)if(typeof obj[method]!=="function")fail(label+" adapter is incomplete.");
    const assertContext=()=>{if(!isCurrent())fail("Account changed during cleanup execution.");};
    let activeLease=null,heartbeat=null,renewal=Promise.resolve(),lockLost=false;
    const acquire=async()=>{assertContext();const lease=await ownerLock.acquire(ownerId,{ttlMs:30000});try{assertContext();const current=await ownerLock.isCurrent(lease);assertContext();if(!current)fail("Owner cleanup lock could not be verified.");activeLease=lease;lockLost=false;return lease;}catch(error){try{await ownerLock.release(lease);}catch{}throw error;}};
    const startHeartbeat=()=>{if(heartbeat)clearInterval(heartbeat);heartbeat=setInterval(()=>{renewal=renewal.then(async()=>{if(!activeLease||lockLost)return;try{activeLease=await ownerLock.renew(activeLease,{ttlMs:30000});}catch{lockLost=true;}});},8000);};
    const stopHeartbeat=async()=>{if(heartbeat)clearInterval(heartbeat);heartbeat=null;await renewal;};
    const assertLease=async()=>{assertContext();await renewal;if(lockLost||!activeLease||!(await ownerLock.isCurrent(activeLease)))fail("Owner cleanup lock was lost or fenced.");assertContext();};
    const release=async lease=>{if(lease){await ownerLock.release(lease);if(activeLease?.token===lease.token)activeLease=null;}};
    const snapshot=async()=>{
      assertContext();
      const cards=localAdapter.readLocalItems(ownerId);
      if(cards&&typeof cards.then==="function")fail("Owner metadata must be read synchronously.");
      const activeIds=referencesIn(cards),metadataDigest=await digest(cards);
      const operations=await collectAll(restoreJournal,ownerId,"Restore journal");
      for(const op of operations){
        if(!op||op.ownerId!==ownerId||!validUuid(op.operationId)||!Array.isArray(op.references)||op.references.length>600)
          fail("Restore journal contains malformed or foreign records.");
      }
      return {activeIds,metadataDigest,operations};
    };
    let manifest=await cleanupJournal.getManifest(ownerId,cleanupId);
    if(!manifest||manifest.ownerId!==ownerId||manifest.cleanupId!==cleanupId||!["reconciled","deleting"].includes(manifest.state)||
       !Array.isArray(manifest.candidates)||manifest.candidates.length>MAX_CANDIDATES)fail("Manifest is not a reconciled cleanup record.");
    const results=[];
    for(const candidate of manifest.candidates){
      if(results.filter(x=>x.state==="deleted").length>=maxDeletes)break;
      if(candidate.state==="deleted"){results.push({localStagedBlobId:candidate.localStagedBlobId,state:"already_deleted"});continue;}
      if(candidate.state!=="eligible_for_delete_review"&&candidate.state!=="delete_intent")continue;
      if(!Number.isFinite(Date.parse(candidate.deleteAfter))||Date.parse(candidate.deleteAfter)>now())continue;
      if(!validUuid(candidate.operationId)||!validUuid(candidate.cloudAssetId)||!validUuid(candidate.localStagedBlobId)||
         !SHA.test(candidate.sha256||"")||!Number.isSafeInteger(candidate.sizeBytes)||candidate.sizeBytes<1)
        fail("Candidate identity or proof is invalid.");
      let lease=null,intent=null,attemptId=null;
      try{
        lease=await acquire();startHeartbeat();
        const fresh=await snapshot();await assertLease();
        if(fresh.metadataDigest!==manifest.metadataDigest)fail("Owner metadata changed since cleanup marking.");
        const {operation,reference}=assertInventories(ownerId,fresh.operations,candidate,fresh.activeIds);
        if(candidate.state==="delete_intent"){
          // Crash recovery: only an exact missing Blob may be finalized, after the same complete recheck.
          const existing=await blobStore.readStagedBlob({ownerId,operationId:candidate.operationId,cloudAssetId:candidate.cloudAssetId,localStagedBlobId:candidate.localStagedBlobId});
          if(existing)fail("A prior delete intent still has a Blob; manual recovery is required.");
          await assertLease();await stopHeartbeat();await release(lease);lease=null;
          lease=await acquire();startHeartbeat();await assertLease();
          manifest=await cleanupJournal.getManifest(ownerId,cleanupId);
          const current=manifest?.candidates?.find(c=>c.localStagedBlobId===candidate.localStagedBlobId);
          if(!manifest||!current||current.state!=="delete_intent"||current.deleteAttemptId!==candidate.deleteAttemptId)
            fail("Delete-intent recovery manifest changed.");
          // The lock was released to obtain a newer fencing epoch. Rebuild every
          // owner-scoped precondition after reacquisition before finalizing recovery.
          const recoveredSnapshot=await snapshot();
          await assertLease();
          if(recoveredSnapshot.metadataDigest!==manifest.metadataDigest)
            fail("Owner metadata changed while recovering the delete intent.");
          assertInventories(ownerId,recoveredSnapshot.operations,candidate,recoveredSnapshot.activeIds);
          const stillMissing=await blobStore.readStagedBlob({ownerId,operationId:candidate.operationId,
            cloudAssetId:candidate.cloudAssetId,localStagedBlobId:candidate.localStagedBlobId});
          if(stillMissing)fail("Delete-intent Blob reappeared during recovery; manual review is required.");
          await assertLease();
          const finalized=await cleanupJournal.finalizeCandidateDeleted({ownerId,cleanupId,expectedRevision:manifest.revision,
            ownerLockEpoch:lease.epoch,localStagedBlobId:candidate.localStagedBlobId,deleteAttemptId:candidate.deleteAttemptId});
          manifest=finalized;results.push({localStagedBlobId:candidate.localStagedBlobId,state:"recovered_deleted"});continue;
        }
        if(!operation||Date.parse(candidate.deleteAfter)>now())fail("Retention or source-state check failed.");
        const attempt=crypto.randomUUID();attemptId=attempt;
        intent=await cleanupJournal.beginCandidateDelete({ownerId,cleanupId,expectedRevision:manifest.revision,
          ownerLockEpoch:lease.epoch,localStagedBlobId:candidate.localStagedBlobId,deleteAttemptId:attempt});
        manifest=intent;
        await assertLease();
        // Re-read the exact manifest identity after the durable intent and before touching bytes.
        const exact=intent.candidates.find(c=>c.localStagedBlobId===candidate.localStagedBlobId);
        if(!exact||exact.state!=="delete_intent"||exact.deleteAttemptId!==attempt||
           exact.operationId!==candidate.operationId||exact.cloudAssetId!==candidate.cloudAssetId||
           exact.sha256!==candidate.sha256||exact.sizeBytes!==candidate.sizeBytes||exact.mimeType!==candidate.mimeType||
           exact.width!==candidate.width||exact.height!==candidate.height)fail("Durable delete intent does not match the exact candidate.");
        await assertLease();
        const result=await blobStore.deleteStagedBlob({ownerId,operationId:candidate.operationId,cloudAssetId:candidate.cloudAssetId,
          localStagedBlobId:candidate.localStagedBlobId,inspectImage,beforeDelete:assertLease,
          proof:{sha256:candidate.sha256,sizeBytes:candidate.sizeBytes,mimeType:candidate.mimeType,width:candidate.width,height:candidate.height}});
        if(result!=="deleted")fail(result==="missing"?"Staged Blob disappeared before exact deletion; intent retained for manual recovery.":"Blob store returned an unknown deletion result.");
        await assertLease();await stopHeartbeat();await release(lease);lease=null;
        lease=await acquire();startHeartbeat();
        await assertLease();
        const latest=await cleanupJournal.getManifest(ownerId,cleanupId);
        const latestCandidate=latest?.candidates?.find(c=>c.localStagedBlobId===candidate.localStagedBlobId);
        if(!latest||latestCandidate?.state!=="delete_intent"||latestCandidate.deleteAttemptId!==attempt)
          fail("Delete intent changed before journal finalization.");
        const final=await cleanupJournal.finalizeCandidateDeleted({ownerId,cleanupId,expectedRevision:latest.revision,
          ownerLockEpoch:lease.epoch,localStagedBlobId:candidate.localStagedBlobId,deleteAttemptId:attempt});
        manifest=final;results.push({localStagedBlobId:candidate.localStagedBlobId,state:"deleted",blobResult:result});
      }finally{await stopHeartbeat();if(lease)try{await release(lease);}catch{}}
    }
    return Object.freeze({state:"processed",processed:results.length,results:Object.freeze(results)});
  }
  globalThis.PWACharacterRestoreCleanupExecutor=Object.freeze({executeEligibleCleanup});
})();