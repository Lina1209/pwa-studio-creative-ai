/* Durable append-only mark journal for staged restore Blob cleanup.
 * This module records candidates only. It has no delete or mutation API.
 */
(() => {
  "use strict";
  const DB="pwa-studio-character-restore-cleanup-journal-v1",VERSION=1,STORE="manifests",PROTOCOL=1;
  const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const SHA=/^[a-f0-9]{64}$/i;
  const MIME=new Set(["image/png","image/jpeg","image/webp"]);
  const fail=m=>{throw new Error(m)};
  const uuid=(v,label)=>{if(typeof v!=="string"||!UUID.test(v))fail("Invalid "+label+".");return v.toLowerCase();};
  const iso=(v,label)=>{if(typeof v!=="string"||!Number.isFinite(Date.parse(v)))fail("Invalid "+label+".");return v;};
  const clone=v=>typeof structuredClone==="function"?structuredClone(v):JSON.parse(JSON.stringify(v));
  const key=(owner,id)=>owner+":"+id;
  function validate(row){
    if(!row||row.protocolVersion!==PROTOCOL||row.id!==key(row.ownerId,row.cleanupId))fail("Invalid cleanup manifest identity.");
    uuid(row.ownerId,"owner ID");uuid(row.cleanupId,"cleanup ID");
    if(!["marked","reconciled"].includes(row.state)||!Number.isSafeInteger(row.revision)||row.revision<1||(row.state==="marked"&&row.revision!==1))fail("Invalid cleanup manifest state or revision.");
    if(!Number.isSafeInteger(row.ownerLockEpoch)||row.ownerLockEpoch<1)fail("Invalid owner lock epoch.");
    if(!SHA.test(row.metadataDigest||""))fail("Invalid metadata snapshot digest.");
    if(!Array.isArray(row.candidates)||row.candidates.length<1||row.candidates.length>600)fail("Invalid cleanup candidate list.");
    const ids=new Set(),tuples=new Set();
    for(const c of row.candidates){
      if(!c||typeof c!=="object")fail("Invalid cleanup candidate.");
      uuid(c.operationId,"restore operation ID");uuid(c.cloudAssetId,"cloud asset ID");uuid(c.localStagedBlobId,"staged Blob ID");
      if(!Number.isSafeInteger(c.operationRevision)||c.operationRevision<1)fail("Invalid source operation revision.");
      if(!SHA.test(c.sha256||"")||!Number.isSafeInteger(c.sizeBytes)||c.sizeBytes<1||c.sizeBytes>8*1024*1024||
         !MIME.has(c.mimeType)||!Number.isInteger(c.width)||c.width<1||c.width>12000||!Number.isInteger(c.height)||c.height<1||c.height>12000)fail("Invalid staged Blob proof.");
      iso(c.markedAt,"candidate mark timestamp");iso(c.deleteAfter,"candidate retention timestamp");
      if(Date.parse(c.deleteAfter)<=Date.parse(c.markedAt))fail("Cleanup retention window must be positive.");
      if(!["marked","retained","eligible_for_delete_review"].includes(c.state))fail("Invalid cleanup candidate state.");
      if(c.state==="retained"&&!["metadata_changed","source_changed","reference_changed","proof_changed","blob_missing","inventory_incomplete"].includes(c.reasonCode))fail("Invalid retained candidate reason.");
      if(c.state==="eligible_for_delete_review")iso(c.recheckedAt,"candidate recheck timestamp");
      if(c.state==="marked"&&(c.reasonCode!==undefined||c.recheckedAt!==undefined))fail("Unreconciled candidate has premature outcome metadata.");
      const tuple=c.operationId+":"+c.cloudAssetId+":"+c.localStagedBlobId;
      if(ids.has(c.localStagedBlobId)||tuples.has(tuple))fail("Duplicate staged Blob cleanup candidate.");
      ids.add(c.localStagedBlobId);tuples.add(tuple);
    }
    iso(row.createdAt,"manifest creation timestamp");
    return row;
  }
  function open(){
    return new Promise((resolve,reject)=>{
      const req=indexedDB.open(DB,VERSION);
      req.onupgradeneeded=()=>{const db=req.result;if(!db.objectStoreNames.contains(STORE)){const store=db.createObjectStore(STORE,{keyPath:"id"});store.createIndex("byOwner","ownerId",{unique:false});}};
      req.onsuccess=()=>resolve(req.result);
      req.onerror=()=>reject(req.error||new Error("Cleanup journal open failed."));
      req.onblocked=()=>reject(new Error("Cleanup journal upgrade is blocked."));
    });
  }
  async function createManifest(input){
    const ownerId=uuid(input?.ownerId,"owner ID"),cleanupId=uuid(input?.cleanupId,"cleanup ID");
    const row={id:key(ownerId,cleanupId),protocolVersion:PROTOCOL,ownerId,cleanupId,state:"marked",revision:1,
      ownerLockEpoch:input.ownerLockEpoch,metadataDigest:input.metadataDigest,
      candidates:clone(input.candidates).map(candidate=>({...candidate,state:"marked"})),createdAt:input.createdAt||new Date().toISOString()};
    validate(row);
    const db=await open();
    try{
      await new Promise((resolve,reject)=>{
        const tx=db.transaction(STORE,"readwrite"),store=tx.objectStore(STORE),get=store.get(row.id);
        let result;
        get.onsuccess=()=>{
          if(get.result){
            validate(get.result);
            if(JSON.stringify(get.result)!==JSON.stringify(row)){try{tx.abort();}catch{}return;}
            result=clone(get.result);return;
          }
          store.add(row);result=clone(row);
        };
        get.onerror=()=>{try{tx.abort();}catch{}};
        tx.oncomplete=()=>resolve(result);
        tx.onerror=()=>reject(tx.error||new Error("Cleanup manifest write failed."));
        tx.onabort=()=>reject(tx.error||new Error("Cleanup manifest identity collision or write aborted."));
      });
      const saved=await getManifest(ownerId,cleanupId);
      if(!saved)fail("Cleanup manifest read-back failed.");
      return saved;
    }finally{db.close();}
  }
  async function getManifest(ownerValue,cleanupValue){
    const owner=uuid(ownerValue,"owner ID"),cleanup=uuid(cleanupValue,"cleanup ID"),db=await open();
    try{return await new Promise((resolve,reject)=>{
      const req=db.transaction(STORE,"readonly").objectStore(STORE).get(key(owner,cleanup));
      req.onsuccess=()=>{if(!req.result){resolve(null);return;}validate(req.result);if(req.result.ownerId!==owner)fail("Cleanup manifest owner mismatch.");resolve(clone(req.result));};
      req.onerror=()=>reject(req.error||new Error("Cleanup manifest read failed."));
    });}finally{db.close();}
  }
  async function listPage(ownerValue,{limit=25,cursor=null}={}){
    const owner=uuid(ownerValue,"owner ID");
    if(!Number.isInteger(limit)||limit<1||limit>100)fail("Page limit must be 1..100.");
    let after="";
    if(cursor!==null){
      if(typeof cursor!=="string"||cursor.length>512)fail("Invalid cleanup cursor.");
      let parsed;try{parsed=JSON.parse(atob(cursor));}catch{fail("Invalid cleanup cursor.");}
      if(parsed.v!==1||parsed.owner!==owner||typeof parsed.after!=="string"||!parsed.after.startsWith(owner+":"))fail("Cleanup cursor owner mismatch.");
      after=parsed.after;
    }
    const db=await open();
    try{return await new Promise((resolve,reject)=>{
      const tx=db.transaction(STORE,"readonly"),req=tx.objectStore(STORE).index("byOwner").openCursor(IDBKeyRange.only(owner),"next");
      const rows=[];let more=false;
      req.onsuccess=()=>{const c=req.result;if(!c){rows.forEach(validate);resolve({items:clone(rows),nextCursor:null});return;}
        if(c.primaryKey>after){if(rows.length===limit){more=true;rows.forEach(validate);resolve({items:clone(rows),nextCursor:btoa(JSON.stringify({v:1,owner,after:rows.at(-1).id}))});return;}rows.push(c.value);}
        c.continue();
      };
      req.onerror=()=>reject(req.error||new Error("Cleanup manifest page read failed."));
    });}finally{db.close();}
  }
  async function reconcileManifest(input){
    const owner=uuid(input?.ownerId,"owner ID"),cleanup=uuid(input?.cleanupId,"cleanup ID");
    if(!Number.isSafeInteger(input?.expectedRevision)||input.expectedRevision<1||!Array.isArray(input.candidates))fail("Invalid cleanup reconciliation request.");
    let updated=null;
    const db=await open();
    try{
      await new Promise((resolve,reject)=>{
        const tx=db.transaction(STORE,"readwrite"),store=tx.objectStore(STORE),req=store.get(key(owner,cleanup));
        req.onsuccess=()=>{
          const row=req.result;
          if(!row){try{tx.abort();}catch{}return;}
          validate(row);
          if(row.ownerId!==owner||row.state!=="marked"||row.revision!==input.expectedRevision||input.candidates.length!==row.candidates.length){try{tx.abort();}catch{}return;}
          const next=row.candidates.map((candidate,index)=>{
            const outcome=input.candidates[index];
            const identity=["operationId","operationRevision","cloudAssetId","localStagedBlobId","sha256","sizeBytes","mimeType","width","height","markedAt","deleteAfter"];
            if(!outcome||identity.some(field=>outcome[field]!==candidate[field])||
               !["retained","eligible_for_delete_review"].includes(outcome.state))fail("Cleanup reconciliation attempted to change candidate identity.");
            const result={...candidate,state:outcome.state};
            if(outcome.state==="retained")result.reasonCode=outcome.reasonCode;
            if(outcome.state==="eligible_for_delete_review")result.recheckedAt=iso(outcome.recheckedAt,"candidate recheck timestamp");
            return result;
          });
          row.candidates=next;row.state="reconciled";row.revision+=1;row.updatedAt=new Date().toISOString();
          validate(row);store.put(row);updated=clone(row);
        };
        req.onerror=()=>{try{tx.abort();}catch{}};
        tx.oncomplete=()=>resolve();
        tx.onerror=()=>reject(tx.error||new Error("Cleanup manifest reconciliation failed."));
        tx.onabort=()=>reject(tx.error||new Error("Cleanup manifest reconciliation was fenced or stale."));
      });
    }finally{db.close();}
    if(!updated)fail("Cleanup manifest reconciliation rejected: stale revision, owner, or state.");
    return updated;
  }
  globalThis.PWACharacterRestoreCleanupJournal=Object.freeze({protocolVersion:PROTOCOL,createManifest,getManifest,listPage,reconcileManifest});
})();
