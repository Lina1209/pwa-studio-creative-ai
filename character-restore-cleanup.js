/* Mark-only staged Blob cleanup planner.
 * Acquires the shared owner lock, proves complete owner inventory, then writes
 * a delayed-retention manifest. It intentionally cannot delete any Blob.
 */
(() => {
 "use strict";
 const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
 const SHA=/^[a-f0-9]{64}$/i,MIME=new Set(["image/png","image/jpeg","image/webp"]);
 const MAX_OPERATIONS=100,MAX_CANDIDATES=600,MAX_BYTES=8*1024*1024;
 const fail=m=>{throw new Error(m)};
 const validUuid=v=>typeof v==="string"&&UUID.test(v);
 const canonical=v=>{if(Array.isArray(v))return "["+v.map(canonical).join(",")+"]";if(v&&typeof v==="object")return "{"+Object.keys(v).sort().map(k=>JSON.stringify(k)+":"+canonical(v[k])).join(",")+"}";return JSON.stringify(v);};
 const sha256=async value=>{const bytes=new TextEncoder().encode(value),hash=await crypto.subtle.digest("SHA-256",bytes);return Array.from(new Uint8Array(hash),x=>x.toString(16).padStart(2,"0")).join("");};
 const uuidFromDigest=hex=>{const a=hex.slice(0,32).split("");a[12]="5";a[16]=((parseInt(a[16],16)&3)|8).toString(16);const s=a.join("");return s.slice(0,8)+"-"+s.slice(8,12)+"-"+s.slice(12,16)+"-"+s.slice(16,20)+"-"+s.slice(20);};
 const proofBlob=async(blob,expected,inspectImage)=>{
   if(!(blob instanceof Blob)||blob.size<1||blob.size>MAX_BYTES||!MIME.has(blob.type))fail("Staged image is missing or has unsupported bytes.");
   const bytes=await blob.arrayBuffer(),hash=await crypto.subtle.digest("SHA-256",bytes);
   const actual={sha256:Array.from(new Uint8Array(hash),x=>x.toString(16).padStart(2,"0")).join(""),sizeBytes:bytes.byteLength,mimeType:blob.type};
   if(actual.sha256!==expected.expectedSha256||actual.sizeBytes!==expected.expectedSizeBytes||actual.mimeType!==expected.expectedMimeType)fail("Staged image proof no longer matches its durable restore checkpoint.");
   const dimensions=await inspectImage(blob);
   if(!dimensions||dimensions.width!==expected.width||dimensions.height!==expected.height)fail("Staged image dimensions no longer match the restore checkpoint.");
   return actual;
 };
 async function markAbortedRestoreBlobs(input){
   const {ownerId,restoreJournal,cleanupJournal,blobStore,localAdapter,ownerLock=globalThis.PWACharacterOwnerCoordinationLock,inspectImage,isCurrent=()=>true}=input||{};
   if(!validUuid(ownerId)||!restoreJournal||!cleanupJournal||!blobStore||!localAdapter||!ownerLock||
      typeof inspectImage!=="function"||typeof isCurrent!=="function")fail("Cleanup marking adapters are incomplete.");
   for(const method of ["listPage","get"])if(typeof restoreJournal[method]!=="function")fail("Restore journal adapter is incomplete.");
   if(typeof cleanupJournal.createManifest!=="function"||typeof blobStore.readStagedBlob!=="function"||
      typeof localAdapter.readLocalItems!=="function")fail("Cleanup marking adapters are incomplete.");
   const assertContext=()=>{if(!isCurrent())fail("Account changed during cleanup marking.");};
   assertContext();
   let lease=null,heartbeat=null,renewal=Promise.resolve(),lost=false;
   try{
     lease=await ownerLock.acquire(ownerId,{ttlMs:30000});
     const renew=async()=>{try{lease=await ownerLock.renew(lease,{ttlMs:30000});}catch{lost=true;}};
     heartbeat=setInterval(()=>{renewal=renewal.then(renew);},8000);
     const assertLease=async()=>{assertContext();await renewal;if(lost||!(await ownerLock.isCurrent(lease)))fail("Owner cleanup lock expired or was fenced.");assertContext();};
     await assertLease();
     const localItems=localAdapter.readLocalItems(ownerId);
     if(localItems&&typeof localItems.then==="function")fail("Local metadata inventory must be synchronous.");
     if(!Array.isArray(localItems)||localItems.length>100)fail("Local metadata inventory is incomplete or invalid.");
     const activeIds=new Set();
     for(const card of localItems){
       if(!card||typeof card!=="object"||(card.referenceImages!=null&&!Array.isArray(card.referenceImages)))fail("Local metadata contains an ambiguous card; cleanup marking stopped.");
       for(const ref of card.referenceImages||[]){if(!ref||typeof ref.id!=="string"||!ref.id.trim())fail("Local reference identity is malformed; cleanup marking stopped.");activeIds.add(ref.id);}
     }
     const metadataDigest=await sha256(canonical(localItems));
     await assertLease();
     let cursor=null,operations=[],pages=0;
     do{
       const page=await restoreJournal.listPage(ownerId,{limit:100,cursor});
       await assertLease();
       if(!page||!Array.isArray(page.items)||page.items.length>100)fail("Restore journal page is invalid.");
       operations.push(...page.items);
       if(operations.length>MAX_OPERATIONS)fail("Owner restore journal exceeds the bounded cleanup inventory; no candidates were marked.");
       cursor=page.nextCursor;
       if(++pages>1)fail("Owner restore journal exceeds one complete bounded page; no candidates were marked.");
     }while(cursor);
     // Build global maps before choosing candidates: another operation may still need the same asset/blob.
     const blobOwners=new Map(),assetOwners=new Map();
     for(const op of operations){
       if(!op||op.ownerId!==ownerId||!validUuid(op.operationId)||!Array.isArray(op.references)||op.references.length>600)fail("Restore journal inventory contains an invalid owner or reference list.");
       for(const ref of op.references){
         if(!validUuid(ref.localStagedBlobId)||!validUuid(ref.cloudAssetId))fail("Restore journal contains malformed staged asset identity.");
         const priorBlob=blobOwners.get(ref.localStagedBlobId)||[];
         priorBlob.push({operationId:op.operationId,state:op.state,referenceState:ref.state});blobOwners.set(ref.localStagedBlobId,priorBlob);
         const priorAsset=assetOwners.get(ref.cloudAssetId)||[];
         priorAsset.push({operationId:op.operationId,state:op.state,localStagedBlobId:ref.localStagedBlobId});assetOwners.set(ref.cloudAssetId,priorAsset);
       }
     }
     const candidates=[],markedAt=new Date().toISOString();
     for(const op of operations){
       await assertLease();
       if(op.state!=="aborted")continue;
       if(op.lease&&Date.parse(op.lease.expiresAt)>Date.now())continue;
       for(const ref of op.references){
         if(ref.state!=="verified_staged")continue;
         const sameBlob=blobOwners.get(ref.localStagedBlobId)||[];
         const sameAsset=assetOwners.get(ref.cloudAssetId)||[];
         if(sameBlob.length!==1||sameAsset.some(x=>x.operationId!==op.operationId))continue;
         if(activeIds.has(ref.localStagedBlobId))continue;
         const blob=await blobStore.readStagedBlob({ownerId,operationId:op.operationId,cloudAssetId:ref.cloudAssetId,localStagedBlobId:ref.localStagedBlobId});
         await assertLease();
         if(!blob)fail("A marked staged Blob is missing or its owner/operation identity does not match.");
         const proof=await proofBlob(blob,ref,inspectImage);
         await assertLease();
         candidates.push({operationId:op.operationId,operationRevision:op.revision,cloudAssetId:ref.cloudAssetId,
           localStagedBlobId:ref.localStagedBlobId,sha256:proof.sha256,sizeBytes:proof.sizeBytes,mimeType:proof.mimeType,
           width:ref.width,height:ref.height,markedAt,deleteAfter:new Date(Date.now()+86400000).toISOString()});
         if(candidates.length>MAX_CANDIDATES)fail("Cleanup candidate batch exceeds the 600-reference safety limit.");
       }
     }
     if(!candidates.length)return Object.freeze({state:"no_candidates",candidateCount:0,metadataDigest});
     await assertLease();
     const identity=canonical({ownerId,metadataDigest,candidates:candidates.map(({operationId,operationRevision,cloudAssetId,localStagedBlobId,sha256,sizeBytes,mimeType,width,height})=>({operationId,operationRevision,cloudAssetId,localStagedBlobId,sha256,sizeBytes,mimeType,width,height}))});
     const cleanupId=uuidFromDigest(await sha256(identity));
     const existingManifest=typeof cleanupJournal.getManifest==="function"?await cleanupJournal.getManifest(ownerId,cleanupId):null;
     await assertLease();
     const manifest=existingManifest||await cleanupJournal.createManifest({ownerId,cleanupId,ownerLockEpoch:lease.epoch,metadataDigest,candidates});
     await assertLease();
     return Object.freeze({state:"marked",cleanupId,revision:manifest.revision,candidateCount:manifest.candidates.length,deleteAfter:manifest.candidates.reduce((max,x)=>Date.parse(x.deleteAfter)>max?Date.parse(x.deleteAfter):max,0)});
   }finally{
     if(heartbeat)clearInterval(heartbeat);
     await renewal;
     if(lease)try{await ownerLock.release(lease);}catch{}
   }
 }
 async function inspectMarkedManifest(input){
   const {ownerId,cleanupId,restoreJournal,cleanupJournal,blobStore,localAdapter,ownerLock=globalThis.PWACharacterOwnerCoordinationLock,inspectImage,isCurrent=()=>true}=input||{};
   if(!validUuid(ownerId)||!validUuid(cleanupId)||!restoreJournal||!cleanupJournal||!blobStore||!localAdapter||!ownerLock||
      typeof inspectImage!=="function"||typeof isCurrent!=="function"||typeof cleanupJournal.getManifest!=="function")fail("Cleanup recheck adapters are incomplete.");
   const assertContext=()=>{if(!isCurrent())fail("Account changed during cleanup recheck.");};
   assertContext();
   let lease=null,heartbeat=null,renewal=Promise.resolve(),lost=false;
   try{
     lease=await ownerLock.acquire(ownerId,{ttlMs:30000});
     const renew=async()=>{try{lease=await ownerLock.renew(lease,{ttlMs:30000});}catch{lost=true;}};
     heartbeat=setInterval(()=>{renewal=renewal.then(renew);},8000);
     const assertLease=async()=>{assertContext();await renewal;if(lost||!(await ownerLock.isCurrent(lease)))fail("Owner cleanup lock expired or was fenced.");assertContext();};
     await assertLease();
     const manifest=await cleanupJournal.getManifest(ownerId,cleanupId);
     if(!manifest||manifest.ownerId!==ownerId||manifest.cleanupId!==cleanupId||manifest.state!=="marked")fail("Marked cleanup manifest was not found for this owner.");
     const now=Date.now();
     if(manifest.candidates.some(c=>Date.parse(c.deleteAfter)>now))
       return Object.freeze({state:"retention_pending",candidateCount:manifest.candidates.length,deleteAfter:Math.max(...manifest.candidates.map(c=>Date.parse(c.deleteAfter)))});
     const localItems=localAdapter.readLocalItems(ownerId);
     if(localItems&&typeof localItems.then==="function")fail("Local metadata inventory must be synchronous.");
     if(!Array.isArray(localItems)||localItems.length>100)fail("Local metadata inventory is incomplete or invalid.");
     const metadataDigestNow=await sha256(canonical(localItems));
     await assertLease();
     if(metadataDigestNow!==manifest.metadataDigest)return Object.freeze({state:"blocked_metadata_changed",eligibleCount:0});
     const activeIds=new Set();
     for(const card of localItems){
       if(!card||typeof card!=="object"||(card.referenceImages!=null&&!Array.isArray(card.referenceImages)))fail("Local metadata contains an ambiguous card.");
       for(const ref of card.referenceImages||[]){if(!ref||typeof ref.id!=="string"||!ref.id.trim())fail("Local reference identity is malformed.");activeIds.add(ref.id);}
     }
     const page=await restoreJournal.listPage(ownerId,{limit:100,cursor:null});
     await assertLease();
     if(!page||!Array.isArray(page.items)||page.items.length>MAX_OPERATIONS||page.nextCursor!==null)
       return Object.freeze({state:"blocked_incomplete_inventory",eligibleCount:0});
     const operations=page.items;
     const blobRefs=new Map(),assetRefs=new Map();
     for(const op of operations){
       if(!op||op.ownerId!==ownerId||!validUuid(op.operationId)||!Array.isArray(op.references))fail("Restore journal inventory is malformed.");
       for(const ref of op.references){
         const blobs=blobRefs.get(ref.localStagedBlobId)||[];blobs.push(op.operationId);blobRefs.set(ref.localStagedBlobId,blobs);
         const assets=assetRefs.get(ref.cloudAssetId)||[];assets.push(op.operationId);assetRefs.set(ref.cloudAssetId,assets);
       }
     }
     const eligible=[];
     for(const candidate of manifest.candidates){
       await assertLease();
       const source=operations.find(op=>op.operationId===candidate.operationId);
       if(!source||source.state!=="aborted"||source.revision!==candidate.operationRevision||
          (source.lease&&Date.parse(source.lease.expiresAt)>Date.now()))
         return Object.freeze({state:"blocked_source_changed",eligibleCount:0,operationId:candidate.operationId});
       const matching=source.references.filter(ref=>ref.localStagedBlobId===candidate.localStagedBlobId&&ref.cloudAssetId===candidate.cloudAssetId&&ref.state==="verified_staged");
       if(matching.length!==1||activeIds.has(candidate.localStagedBlobId)||
          (blobRefs.get(candidate.localStagedBlobId)||[]).length!==1||
          (assetRefs.get(candidate.cloudAssetId)||[]).some(id=>id!==candidate.operationId))
         return Object.freeze({state:"blocked_reference_or_mapping_changed",eligibleCount:0,operationId:candidate.operationId});
       const ref=matching[0];
       if(ref.expectedSha256!==candidate.sha256||ref.expectedSizeBytes!==candidate.sizeBytes||
          ref.expectedMimeType!==candidate.mimeType||ref.width!==candidate.width||ref.height!==candidate.height)
         return Object.freeze({state:"blocked_checkpoint_proof_changed",eligibleCount:0,operationId:candidate.operationId});
       const blob=await blobStore.readStagedBlob({ownerId,operationId:candidate.operationId,cloudAssetId:candidate.cloudAssetId,localStagedBlobId:candidate.localStagedBlobId});
       await assertLease();
       if(!blob)return Object.freeze({state:"blocked_blob_missing_or_identity_changed",eligibleCount:0,localStagedBlobId:candidate.localStagedBlobId});
       try{await proofBlob(blob,ref,inspectImage);}catch(_){return Object.freeze({state:"blocked_blob_integrity_changed",eligibleCount:0,localStagedBlobId:candidate.localStagedBlobId});}
       await assertLease();
       eligible.push(Object.freeze({operationId:candidate.operationId,cloudAssetId:candidate.cloudAssetId,localStagedBlobId:candidate.localStagedBlobId}));
     }
     return Object.freeze({state:"eligible_for_delete_review",eligibleCount:eligible.length,candidates:Object.freeze(eligible)});
   }finally{
     if(heartbeat)clearInterval(heartbeat);
     await renewal;
     if(lease)try{await ownerLock.release(lease);}catch{}
   }
 }
 globalThis.PWACharacterRestoreCleanup=Object.freeze({markAbortedRestoreBlobs,inspectMarkedManifest});
})();
