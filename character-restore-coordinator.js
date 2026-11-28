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
  const LOCAL_REFERENCE_KEY=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(-[a-z0-9_-]{8,80})?$/i;
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
    const expectedSha=expected.expectedSha256??expected.sha256;
    const expectedSize=expected.expectedSizeBytes??expected.sizeBytes;
    const expectedMime=expected.expectedMimeType??expected.mimeType;
    if(typeof actual?.sha256!=="string"||actual.sha256.toLowerCase()!==String(expectedSha).toLowerCase())fail("Image SHA-256 verification failed.");
    if(actual.sizeBytes!==expectedSize)fail("Image byte-size verification failed.");
    if(actual.mimeType!==expectedMime)fail("Image MIME verification failed.");
  };
  async function stageRestoreReferences({ownerId,operationId,manifest,expectedRevision,journal,adapters,isCurrent=()=>true,plan,preview,confirmation,validateConfirmation}) {
    ownerId=uuid(ownerId,"owner ID");operationId=uuid(operationId,"operation ID");
    if(!Array.isArray(manifest)||manifest.length>MAX_REFS)fail("Restore media manifest exceeds the supported limit.");
    if(!Number.isSafeInteger(expectedRevision)||expectedRevision<1)fail("Invalid journal revision.");
    if(!journal||typeof journal.get!=="function"||typeof journal.acquireLease!=="function"||typeof journal.checkpoint!=="function"||typeof journal.releaseLease!=="function")fail("Restore journal adapter is incomplete.");
    for(const name of ["downloadAsset","inspectImage","stageBlob","readStagedBlob"])if(typeof adapters?.[name]!=="function")fail("Missing media adapter: "+name+".");
    if(typeof validateConfirmation!=="function"||!plan||!preview||!confirmation)fail("An explicit issued restore confirmation is required before media staging.");
    const assertConfirmation=()=>{
      if(typeof validateConfirmation!=="function"||validateConfirmation({ownerId,plan,preview,confirmation})!==true)
        fail("Restore confirmation is missing, invalid, expired, or no longer matches this selection.");
    };
    assertConfirmation();
    if(typeof isCurrent!=="function"||!isCurrent())fail("Account is not current.");
    const seen=new Set();
    const refs=manifest.map(item=>{
      const cloudAssetId=uuid(item?.cloudAssetId,"cloud asset ID");
      if(seen.has(cloudAssetId))fail("Duplicate cloud asset in restore manifest.");seen.add(cloudAssetId);
      const characterId=uuid(item.characterId,"cloud character ID");
      const sourceLocalId=uuid(item.sourceLocalId,"local character ID");
      const localReferenceId=typeof item.localReferenceId==="string"?item.localReferenceId:item.id;
      if(typeof localReferenceId!=="string"||!LOCAL_REFERENCE_KEY.test(localReferenceId))fail("Invalid local reference identity in restore manifest.");
      if(typeof item.name!=="string"||!item.name.trim()||item.name.length>120)fail("Invalid reference display name.");
      if(!SHA.test(item.expectedSha256||"")||!Number.isSafeInteger(item.expectedSizeBytes)||item.expectedSizeBytes<1||item.expectedSizeBytes>MAX_BYTES)fail("Invalid expected image digest or size.");
      if(!MIME.has(item.expectedMimeType)||item.type!==item.expectedMimeType)fail("Unsupported or mismatched expected image MIME type.");
      if(!Number.isInteger(item.width)||item.width<1||item.width>12000||!Number.isInteger(item.height)||item.height<1||item.height>12000)fail("Invalid expected image dimensions.");
      return {cloudAssetId,characterId,sourceLocalId,localReferenceId,name:item.name,type:item.type,expectedSha256:item.expectedSha256.toLowerCase(),expectedSizeBytes:item.expectedSizeBytes,expectedMimeType:item.expectedMimeType,width:item.width,height:item.height,state:"pending",localStagedBlobId:null};
    });
    if(refs.length===0)fail("There are no media references to stage.");
    const selectedCloudIds=confirmation.selectedCloudIds;
    if(!Array.isArray(selectedCloudIds)||selectedCloudIds.length<1||
       refs.some(reference=>!selectedCloudIds.includes(reference.characterId)))
      fail("Restore media manifest is outside the explicitly confirmed character selection.");

    // Bind the staged media manifest to the exact reference inventory reviewed
    // by the planner. Selection membership alone is insufficient: a caller
    // must not omit, add, or substitute an image within a confirmed character.
    if(!Array.isArray(plan.proposedItems))fail("Issued restore plan has no proposed character inventory.");
    const reviewedReferences=[];
    for(const character of plan.proposedItems){
      if(!character?.cloudBackup||!selectedCloudIds.includes(character.cloudBackup.characterId)||
         !Array.isArray(character.cloudBackup.referenceManifest))
        fail("Issued restore plan contains an invalid reviewed reference inventory.");
      for(const reference of character.cloudBackup.referenceManifest){
        reviewedReferences.push({
          cloudAssetId:reference.cloudAssetId,
          characterId:character.cloudBackup.characterId,
          sourceLocalId:character.id,
          localReferenceId:reference.localReferenceId??reference.id,
          name:reference.name,
          type:reference.type,
          expectedSha256:reference.expectedSha256,
          expectedSizeBytes:reference.expectedSizeBytes,
          expectedMimeType:reference.expectedMimeType,
          width:reference.width,
          height:reference.height
        });
      }
    }
    const proofFields=["cloudAssetId","characterId","sourceLocalId","localReferenceId","name","type","expectedSha256","expectedSizeBytes","expectedMimeType","width","height"];
    const proofKey=item=>proofFields.map(field=>item[field]??null);
    const reviewedByAsset=new Map();
    for(const reference of reviewedReferences){
      if(typeof reference.cloudAssetId!=="string"||reviewedByAsset.has(reference.cloudAssetId))
        fail("Reviewed restore plan contains duplicate or invalid cloud media identities.");
      reviewedByAsset.set(reference.cloudAssetId,reference);
    }
    if(reviewedByAsset.size!==refs.length)fail("Restore media manifest is incomplete or contains unreviewed assets.");
    for(const reference of refs){
      const reviewed=reviewedByAsset.get(reference.cloudAssetId);
      if(!reviewed||JSON.stringify(proofKey(reviewed))!==JSON.stringify(proofKey(reference)))
        fail("Restore media manifest differs from the exact reference inventory reviewed by the planner.");
    }
    assertConfirmation();
    const operation=await journal.get(ownerId,operationId);
    assertConfirmation();
    if(!operation||operation.ownerId!==ownerId||operation.operationId!==operationId)fail("Restore operation was not found for this owner.");
    if(operation.revision!==expectedRevision||!["planned","staging","paused_retryable"].includes(operation.state))fail("Restore operation is not at the expected checkpoint.");
    assertConfirmation();
    const lease=await journal.acquireLease(ownerId,operationId,{ttlMs:60000});
    let leasedOperation;
    try{
      assertConfirmation();
      leasedOperation=await journal.get(ownerId,operationId);
      assertConfirmation();
      if(!leasedOperation||leasedOperation.ownerId!==ownerId||leasedOperation.operationId!==operationId||
         leasedOperation.revision!==expectedRevision+1||leasedOperation.leaseEpoch!==lease.epoch)
        fail("Restore operation changed while its lease was being acquired.");
    }catch(error){
      try{await journal.releaseLease(ownerId,operationId,lease);}catch{}
      throw error;
    }
    let revision=leasedOperation.revision;
    let state=leasedOperation.state;
    let staged=0;
    let leaseLost=null;
    let renewalInFlight=null;
    const renewLease=()=>{
      if(renewalInFlight)return renewalInFlight;
      renewalInFlight=journal.renewLease(ownerId,operationId,lease,{ttlMs:60000})
        .catch(error=>{leaseLost=error;})
        .finally(()=>{renewalInFlight=null;});
      return renewalInFlight;
    };
    const assertLease=()=>{if(leaseLost)fail("Restore lease was lost; staging must pause and resume safely.");};
    const heartbeat=setInterval(()=>{if(!leaseLost)void renewLease();},20000);
    try{
      assertConfirmation();
      if(!isCurrent())fail("Account changed before media staging.");
      assertConfirmation();
      if(state==="planned"){
        const row=await journal.checkpoint({ownerId,operationId,leaseToken:lease.token,leaseEpoch:lease.epoch,expectedRevision:revision,state:"staging",references:refs.map(r=>({...r,localStagedBlobId:uuid(crypto.randomUUID(),"staged Blob ID")}))});
        revision=row.revision;state=row.state;
        assertConfirmation();
      } else if(state==="paused_retryable"){
        const pausedRecord=await journal.get(ownerId,operationId);
        const row=await journal.checkpoint({ownerId,operationId,leaseToken:lease.token,leaseEpoch:lease.epoch,expectedRevision:revision,state:"staging",references:pausedRecord.references});
        revision=row.revision;state=row.state;
        assertConfirmation();
      }
      const persisted=await journal.get(ownerId,operationId);
      assertConfirmation();
      assertLease();
      if(!isCurrent())fail("Account changed before staging checkpoint verification.");
      if(!persisted||persisted.revision!==revision||persisted.state!=="staging")fail("Restore checkpoint changed before staging.");
      const savedRefs=persisted.references;
      if(savedRefs.length!==refs.length)fail("Persisted restore manifest does not match the requested media.");
      for(let i=0;i<refs.length;i++){
        assertLease();
        if(!isCurrent())fail("Account changed during media staging.");
        const expected=refs[i],saved=savedRefs[i];
        if(saved.cloudAssetId!==expected.cloudAssetId||saved.expectedSha256!==expected.expectedSha256||saved.expectedSizeBytes!==expected.expectedSizeBytes||saved.expectedMimeType!==expected.expectedMimeType)fail("Persisted media checkpoint differs from the requested manifest.");
        let localId=saved.localStagedBlobId;
        if(saved.state==="verified_staged"){
          const existing=await adapters.readStagedBlob({ownerId,operationId,cloudAssetId:expected.cloudAssetId,localStagedBlobId:localId});
          const proof=await digestHex(existing);proofMatches(proof,expected);
          const dimensions=await adapters.inspectImage(existing);
          if(dimensions?.width!==expected.width||dimensions?.height!==expected.height)fail("Staged image dimensions verification failed.");
          staged++;continue;
        }
        assertConfirmation();
        const downloaded=await adapters.downloadAsset({ownerId,operationId,cloudAssetId:expected.cloudAssetId});
        assertConfirmation();
        assertLease();
        if(!isCurrent())fail("Account changed while downloading a media asset.");
        const proof=await digestHex(downloaded);assertLease();proofMatches(proof,expected);
        const dimensions=await adapters.inspectImage(downloaded);assertLease();
        if(!dimensions||dimensions.width!==expected.width||dimensions.height!==expected.height)fail("Downloaded image dimensions verification failed.");
        assertLease();
        assertConfirmation();
        const stored=await adapters.stageBlob({ownerId,operationId,cloudAssetId:expected.cloudAssetId,localStagedBlobId:localId,blob:downloaded,proof:{...proof,width:dimensions.width,height:dimensions.height}});
        assertConfirmation();
        if(!stored||stored.localStagedBlobId!==localId)fail("Staged Blob adapter returned an unexpected identity.");
        if(!isCurrent())fail("Account changed after staging a media asset.");
        assertLease();
        const readBack=await adapters.readStagedBlob({ownerId,operationId,cloudAssetId:expected.cloudAssetId,localStagedBlobId:localId});
        const readProof=await digestHex(readBack);assertLease();proofMatches(readProof,expected);
        const readDimensions=await adapters.inspectImage(readBack);assertLease();
        if(!readDimensions||readDimensions.width!==expected.width||readDimensions.height!==expected.height)fail("Staged Blob read-back dimensions verification failed.");
        assertConfirmation();
        saved.state="verified_staged";
        const updated=await journal.checkpoint({ownerId,operationId,leaseToken:lease.token,leaseEpoch:lease.epoch,expectedRevision:revision,state:"staging",references:savedRefs});
        revision=updated.revision;staged++;
        assertConfirmation();
      }
      await renewalInFlight;
      assertLease();
      if(!isCurrent())fail("Account changed before staging completion.");
      assertConfirmation();
      const ready=await journal.checkpoint({ownerId,operationId,leaseToken:lease.token,leaseEpoch:lease.epoch,expectedRevision:revision,state:"ready_to_activate",references:savedRefs});
      revision=ready.revision;state=ready.state;
      assertConfirmation();
      return Object.freeze({ownerId,operationId,state,revision,stagedReferences:staged,totalReferences:refs.length,activationRequired:true});
    }catch(error){
      try{
        const current=await journal.get(ownerId,operationId);
        if(current&&["staging","ready_to_activate"].includes(current.state)&&current.revision===revision&&isCurrent()){
          const paused=await journal.checkpoint({ownerId,operationId,leaseToken:lease.token,leaseEpoch:lease.epoch,expectedRevision:revision,state:"paused_retryable",references:current.references});
          revision=paused.revision;
        }
      }catch{/* preserve the original failure; lease expiry permits a later safe retry */}
      throw error;
    }finally{
      clearInterval(heartbeat);
      if(renewalInFlight)await renewalInFlight;
      try{await journal.releaseLease(ownerId,operationId,lease);}catch{/* expired/stale leases are fenced by epoch */}
    }
  }
  globalThis.PWACharacterRestoreCoordinator=Object.freeze({stageRestoreReferences});
})();
