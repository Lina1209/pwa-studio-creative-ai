/* Staging-only Character Library restore coordinator.
 * Injected adapters keep network, storage and UI outside this module.
 * It verifies received bytes and staged read-back before checkpointing.
 * It deliberately does NOT activate local metadata.
 */
(() => {
  "use strict";
  const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const SHA=/^[a-f0-9]{64}$/i;
  const MIME=new Set(["image/png","image/jpeg","image/webp"]);
  const MAX_BYTES=8*1024*1024, MAX_REFS=600;
  const fail=m=>{throw new Error(m)};
  const uuid=(v,label)=>{if(typeof v!=="string"||!UUID.test(v))fail("Invalid "+label+".");return v.toLowerCase();};
  const digestHex=async blob=>{
    if(!(blob instanceof Blob))fail("Media adapter did not return a Blob.");
    if(blob.size<1||blob.size>MAX_BYTES)fail("Image byte size is outside the allowed limit.");
    if(!MIME.has(blob.type))fail("Image MIME type is not supported.");
    if(!globalThis.crypto?.subtle)fail("SHA-256 is unavailable in this browser.");
    const bytes=await blob.arrayBuffer();
    const hash=await crypto.subtle.digest("SHA-256",bytes);
    return {sha256:Array.from(new Uint8Array(hash),b=>b.toString(16).padStart(2,"0")).join(""),sizeBytes:bytes.byteLength,mimeType:blob.type};
  };
  const proofMatches=(actual,expected)=>{
    if(actual.sha256.toLowerCase()!==expected.sha256.toLowerCase())fail("Image SHA-256 verification failed.");
    if(actual.sizeBytes!==expected.sizeBytes)fail("Image byte-size verification failed.");
    if(actual.mimeType!==expected.mimeType)fail("Image MIME verification failed.");
  };
  async function stageRestoreReferences({ownerId,operationId,manifest,expectedRevision,journal,adapters,isCurrent=()=>true}) {
    ownerId=uuid(ownerId,"owner ID");operationId=uuid(operationId,"operation ID");
    if(!Array.isArray(manifest)||manifest.length>MAX_REFS)fail("Restore media manifest exceeds the supported limit.");
    if(!Number.isSafeInteger(expectedRevision)||expectedRevision<1)fail("Invalid journal revision.");
    if(!journal||typeof journal.get!=="function"||typeof journal.acquireLease!=="function"||typeof journal.checkpoint!=="function"||typeof journal.releaseLease!=="function")fail("Restore journal adapter is incomplete.");
    for(const name of ["downloadAsset","inspectImage","stageBlob","readStagedBlob"])if(typeof adapters?.[name]!=="function")fail("Missing media adapter: "+name+".");
    if(typeof isCurrent!=="function"||!isCurrent())fail("Account is not current.");
    const seen=new Set();
    const refs=manifest.map(item=>{
      const cloudAssetId=uuid(item?.cloudAssetId,"cloud asset ID");
      if(seen.has(cloudAssetId))fail("Duplicate cloud asset in restore manifest.");seen.add(cloudAssetId);
      if(!SHA.test(item.expectedSha256||"")||!Number.isSafeInteger(item.expectedSizeBytes)||item.expectedSizeBytes<1||item.expectedSizeBytes>MAX_BYTES)fail("Invalid expected image digest or size.");
      if(!MIME.has(item.expectedMimeType))fail("Unsupported expected image MIME type.");
      if(!Number.isInteger(item.width)||item.width<1||item.width>12000||!Number.isInteger(item.height)||item.height<1||item.height>12000)fail("Invalid expected image dimensions.");
      return {cloudAssetId,expectedSha256:item.expectedSha256.toLowerCase(),expectedSizeBytes:item.expectedSizeBytes,expectedMimeType:item.expectedMimeType,width:item.width,height:item.height,state:"pending",localStagedBlobId:null};
    });
    if(refs.length===0)fail("There are no media references to stage.");
    const operation=await journal.get(ownerId,operationId);
    if(!operation||operation.ownerId!==ownerId||operation.operationId!==operationId)fail("Restore operation was not found for this owner.");
    if(operation.revision!==expectedRevision||!["planned","staging","paused_retryable"].includes(operation.state))fail("Restore operation is not at the expected checkpoint.");
    const lease=await journal.acquireLease(ownerId,operationId,{ttlMs:60000});
    const leasedOperation=await journal.get(ownerId,operationId);
    if(!leasedOperation||leasedOperation.ownerId!==ownerId||leasedOperation.operationId!==operationId||
       leasedOperation.revision!==expectedRevision+1||leasedOperation.leaseEpoch!==lease.epoch){
      try{await journal.releaseLease(ownerId,operationId,lease);}catch{}
      fail("Restore operation changed while its lease was being acquired.");
    }
    let revision=leasedOperation.revision;
    let state=leasedOperation.state;
    let staged=0;
    try{
      if(!isCurrent())fail("Account changed before media staging.");
      if(state==="planned"){
        const row=await journal.checkpoint({ownerId,operationId,leaseToken:lease.token,leaseEpoch:lease.epoch,expectedRevision:revision,state:"staging",references:refs.map(r=>({...r,localStagedBlobId:uuid(crypto.randomUUID(),"staged Blob ID")}))});
        revision=row.revision;state=row.state;
      } else if(state==="paused_retryable"){
        const pausedRecord=await journal.get(ownerId,operationId);
        const row=await journal.checkpoint({ownerId,operationId,leaseToken:lease.token,leaseEpoch:lease.epoch,expectedRevision:revision,state:"staging",references:pausedRecord.references});
        revision=row.revision;state=row.state;
      }
      const persisted=await journal.get(ownerId,operationId);
      if(!persisted||persisted.revision!==revision||persisted.state!=="staging")fail("Restore checkpoint changed before staging.");
      const savedRefs=persisted.references;
      if(savedRefs.length!==refs.length)fail("Persisted restore manifest does not match the requested media.");
      for(let i=0;i<refs.length;i++){
        if(!isCurrent())fail("Account changed during media staging.");
        const expected=refs[i],saved=savedRefs[i];
        if(saved.cloudAssetId!==expected.cloudAssetId||saved.expectedSha256!==expected.expectedSha256||saved.expectedSizeBytes!==expected.expectedSizeBytes||saved.expectedMimeType!==expected.expectedMimeType)fail("Persisted media checkpoint differs from the requested manifest.");
        let localId=saved.localStagedBlobId;
        if(saved.state==="verified_staged"){
          const existing=await adapters.readStagedBlob({ownerId,operationId,localStagedBlobId:localId});
          const proof=await digestHex(existing);proofMatches(proof,expected);
          const dimensions=await adapters.inspectImage(existing);
          if(dimensions?.width!==expected.width||dimensions?.height!==expected.height)fail("Staged image dimensions verification failed.");
          staged++;continue;
        }
        const downloaded=await adapters.downloadAsset({ownerId,operationId,cloudAssetId:expected.cloudAssetId});
        if(!isCurrent())fail("Account changed while downloading a media asset.");
        const proof=await digestHex(downloaded);proofMatches(proof,expected);
        const dimensions=await adapters.inspectImage(downloaded);
        if(!dimensions||dimensions.width!==expected.width||dimensions.height!==expected.height)fail("Downloaded image dimensions verification failed.");
        const stored=await adapters.stageBlob({ownerId,operationId,cloudAssetId:expected.cloudAssetId,localStagedBlobId:localId,blob:downloaded,proof:{...proof,width:dimensions.width,height:dimensions.height}});
        if(!stored||stored.localStagedBlobId!==localId)fail("Staged Blob adapter returned an unexpected identity.");
        if(!isCurrent())fail("Account changed after staging a media asset.");
        const readBack=await adapters.readStagedBlob({ownerId,operationId,localStagedBlobId:localId});
        const readProof=await digestHex(readBack);proofMatches(readProof,expected);
        const readDimensions=await adapters.inspectImage(readBack);
        if(!readDimensions||readDimensions.width!==expected.width||readDimensions.height!==expected.height)fail("Staged Blob read-back dimensions verification failed.");
        saved.state="verified_staged";
        const updated=await journal.checkpoint({ownerId,operationId,leaseToken:lease.token,leaseEpoch:lease.epoch,expectedRevision:revision,state:"staging",references:savedRefs});
        revision=updated.revision;staged++;
      }
      if(!isCurrent())fail("Account changed before staging completion.");
      const ready=await journal.checkpoint({ownerId,operationId,leaseToken:lease.token,leaseEpoch:lease.epoch,expectedRevision:revision,state:"ready_to_activate",references:savedRefs});
      revision=ready.revision;state=ready.state;
      return Object.freeze({ownerId,operationId,state,revision,stagedReferences:staged,totalReferences:refs.length,activationRequired:true});
    }catch(error){
      try{
        const current=await journal.get(ownerId,operationId);
        if(current&&current.state==="staging"&&current.revision===revision&&isCurrent()){
          const paused=await journal.checkpoint({ownerId,operationId,leaseToken:lease.token,leaseEpoch:lease.epoch,expectedRevision:revision,state:"paused_retryable",references:current.references});
          revision=paused.revision;
        }
      }catch{/* preserve the original failure; lease expiry permits a later safe retry */}
      throw error;
    }finally{
      try{await journal.releaseLease(ownerId,operationId,lease);}catch{/* expired/stale leases are fenced by epoch */}
    }
  }
  globalThis.PWACharacterRestoreCoordinator=Object.freeze({stageRestoreReferences});
})();
