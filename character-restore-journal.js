/* Durable, owner-bound checkpoint journal for Character Library restore.
 * Isolated IndexedDB database. No network, UI, media reads, or activation side effects.
 */
(() => {
  "use strict";
  const DB = "pwa-studio-character-restore-journal-v1";
  const VERSION = 1;
  const STORE = "operations";
  const PROTOCOL = 1;
  const LOCAL_REFERENCE_KEY = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(-[a-z0-9_-]{8,80})?$/i;
  const STATES = new Set(["planning","planned","staging","ready_to_activate","activating","committed","paused_retryable","conflict","aborted","activation_uncertain"]);
  const NEXT = {
    planning:["planned","paused_retryable","conflict","aborted"],
    planned:["staging","paused_retryable","conflict","aborted"],
    staging:["ready_to_activate","paused_retryable","conflict","aborted"],
    ready_to_activate:["activating","paused_retryable","conflict","aborted"],
    activating:["committed","activation_uncertain","paused_retryable","conflict"],
    paused_retryable:["planning","planned","staging","ready_to_activate","committed","conflict","aborted"],
    activation_uncertain:["committed","conflict","paused_retryable"],
    committed:[], conflict:[], aborted:[]
  };
  const fail = message => { throw new Error(message); };
  const uuid = (v,label) => {
    if(typeof v!=="string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(v)) fail("Invalid "+label+".");
    return v.toLowerCase();
  };
  const str = (v,label,max=180) => {
    if(typeof v!=="string" || !v.trim() || v.length>max) fail("Invalid "+label+".");
    return v;
  };
  const iso = (v,label) => {
    if(typeof v!=="string" || !Number.isFinite(Date.parse(v))) fail("Invalid "+label+".");
    return v;
  };
  const clone = v => typeof structuredClone==="function" ? structuredClone(v) : JSON.parse(JSON.stringify(v));
  const key = (owner,id) => owner+":"+id;
  const now = () => new Date().toISOString();

  function validate(r) {
    if(!r || r.protocolVersion!==PROTOCOL || r.id!==key(r.ownerId,r.operationId)) fail("Invalid restore journal identity.");
    uuid(r.ownerId,"owner ID"); uuid(r.operationId,"operation ID");
    if(!STATES.has(r.state)) fail("Invalid restore operation state.");
    if(!Number.isSafeInteger(r.revision) || r.revision<1) fail("Invalid journal revision.");
    if(!Number.isSafeInteger(r.leaseEpoch) || r.leaseEpoch<0) fail("Invalid lease epoch.");
    str(r.localBaseFingerprint,"local base fingerprint",128);
    str(r.snapshotId,"snapshot identity",200);
    if(!Array.isArray(r.selectedCharacterIds) || r.selectedCharacterIds.length>100) fail("Invalid selected character list.");
    const ids=new Set();
    for(const id of r.selectedCharacterIds){uuid(id,"selected cloud character ID");if(ids.has(id))fail("Duplicate selected character.");ids.add(id);}
    if(!r.page || typeof r.page!=="object" || !Number.isSafeInteger(r.page.count) || r.page.count<0 || r.page.count>10000) fail("Invalid page checkpoint.");
    if(r.page.cursor!==null) str(r.page.cursor,"page cursor",512);
    if(r.page.digest!==null && !/^[a-f0-9]{64}$/i.test(r.page.digest)) fail("Invalid page digest.");
    if(!Array.isArray(r.references) || r.references.length>600) fail("Invalid restore reference list.");
    const refs=new Set();
    for(const x of r.references){
      if(!x || typeof x!=="object") fail("Invalid reference checkpoint.");
      uuid(x.cloudAssetId,"cloud asset ID"); uuid(x.localStagedBlobId,"staged Blob ID");
      uuid(x.characterId,"cloud character ID"); uuid(x.sourceLocalId,"local character ID");
      if(typeof x.localReferenceId!=="string" || !LOCAL_REFERENCE_KEY.test(x.localReferenceId)) fail("Invalid local reference identity.");
      str(x.name,"reference display name",120);
      if(!["image/png","image/jpeg","image/webp"].includes(x.type)) fail("Invalid reference display MIME type.");
      if(refs.has(x.cloudAssetId)) fail("Duplicate cloud asset checkpoint.");
      refs.add(x.cloudAssetId);
      if(!/^[a-f0-9]{64}$/i.test(x.expectedSha256) || !Number.isSafeInteger(x.expectedSizeBytes) || x.expectedSizeBytes<1 || x.expectedSizeBytes>8*1024*1024) fail("Invalid reference proof.");
      if(!["image/png","image/jpeg","image/webp"].includes(x.expectedMimeType) || x.type!==x.expectedMimeType) fail("Invalid reference MIME type.");
      if(!["pending","staging","verified_staged"].includes(x.state)) fail("Invalid reference state.");
      if(x.width!==null && (!Number.isInteger(x.width)||x.width<1||x.width>12000)) fail("Invalid reference width.");
      if(x.height!==null && (!Number.isInteger(x.height)||x.height<1||x.height>12000)) fail("Invalid reference height.");
    }
    if(r.activation!==null){
      const a=r.activation;
      if(!a||typeof a!=="object"||!/^[a-f0-9]{64}$/i.test(a.baseDigest||"")||!/^[a-f0-9]{64}$/i.test(a.mergedDigest||"")||
         !Number.isSafeInteger(a.intendedCount)||a.intendedCount<1||a.intendedCount>100||
         !Number.isSafeInteger(a.restoredCount)||a.restoredCount<1||a.restoredCount>a.intendedCount||
         a.operationMarker!==r.operationId) fail("Invalid activation intent.");
      iso(a.preparedAt,"activation preparation timestamp");
    }
    if(r.state==="activating" && !r.activation) fail("Activating operation requires a durable activation intent.");
    if(r.lease!==null){
      if(!r.lease || typeof r.lease!=="object") fail("Invalid operation lease.");
      str(r.lease.token,"lease token",128); iso(r.lease.expiresAt,"lease expiry");
      if(r.lease.epoch!==r.leaseEpoch) fail("Lease epoch mismatch.");
    }
    iso(r.createdAt,"created timestamp"); iso(r.updatedAt,"updated timestamp");
    return r;
  }

  function open() {
    return new Promise((resolve,reject)=>{
      const req=indexedDB.open(DB,VERSION);
      req.onupgradeneeded=()=>{
        const db=req.result;
        const store=db.objectStoreNames.contains(STORE)?req.transaction.objectStore(STORE):db.createObjectStore(STORE,{keyPath:"id"});
        if(!store.indexNames.contains("byOwner")) store.createIndex("byOwner","ownerId",{unique:false});
      };
      req.onsuccess=()=>resolve(req.result);
      req.onerror=()=>reject(req.error||new Error("Restore journal open failed."));
      req.onblocked=()=>reject(new Error("Restore journal upgrade is blocked by another tab."));
    });
  }
  async function transaction(mode, action) {
    const db=await open();
    try {
      return await new Promise((resolve,reject)=>{
        const tx=db.transaction(STORE,mode), store=tx.objectStore(STORE);
        let result;
        try { result=action(store,tx); } catch(e){try{tx.abort();}catch{} reject(e);return;}
        tx.oncomplete=()=>resolve(result);
        tx.onerror=()=>reject(tx.error||new Error("Restore journal transaction failed."));
        tx.onabort=()=>reject(tx.error||new Error("Restore journal transaction aborted."));
      });
    } finally {db.close();}
  }
  async function read(id) {
    const db=await open();
    try{return await new Promise((resolve,reject)=>{
      const req=db.transaction(STORE,"readonly").objectStore(STORE).get(id);
      req.onsuccess=()=>resolve(req.result||null); req.onerror=()=>reject(req.error);
    });} finally{db.close();}
  }
  async function create(input) {
    const ownerId=uuid(input?.ownerId,"owner ID"), operationId=uuid(input?.operationId||crypto.randomUUID(),"operation ID");
    const stamp=now();
    const row={id:key(ownerId,operationId),protocolVersion:PROTOCOL,ownerId,operationId,state:"planning",revision:1,leaseEpoch:0,lease:null,
      localBaseFingerprint:str(input.localBaseFingerprint,"local base fingerprint",128),
      snapshotId:str(input.snapshotId,"snapshot identity",200),
      selectedCharacterIds:(input.selectedCharacterIds||[]).map(x=>uuid(x,"selected cloud character ID")),
      page:{count:0,cursor:null,digest:null},references:[],activation:null,createdAt:stamp,updatedAt:stamp};
    validate(row);
    await transaction("readwrite",store=>store.add(row));
    const saved=await read(row.id); if(!saved) fail("Restore journal create read-back failed.");
    validate(saved); return clone(saved);
  }
  async function get(ownerValue,operationValue) {
    const owner=uuid(ownerValue,"owner ID"), op=uuid(operationValue,"operation ID");
    const row=await read(key(owner,op)); if(!row)return null;
    validate(row); if(row.ownerId!==owner)fail("Restore journal owner boundary mismatch.");
    return clone(row);
  }
  async function listPage(ownerValue,{limit=25,cursor=null}={}) {
    const owner=uuid(ownerValue,"owner ID");
    if(!Number.isInteger(limit)||limit<1||limit>100)fail("Page limit must be 1..100.");
    let after="";
    if(cursor!==null){
      if(typeof cursor!=="string"||cursor.length>512)fail("Invalid owner cursor.");
      let decoded;try{decoded=JSON.parse(atob(cursor));}catch{fail("Invalid owner cursor.");}
      if(decoded.v!==1||decoded.owner!==owner||typeof decoded.after!=="string"||!decoded.after.startsWith(owner+":"))fail("Cursor owner mismatch.");
      after=decoded.after;
    }
    const db=await open();
    try{return await new Promise((resolve,reject)=>{
      const tx=db.transaction(STORE,"readonly"), req=tx.objectStore(STORE).index("byOwner").openCursor(IDBKeyRange.only(owner),"next");
      const rows=[];let more=false;
      req.onsuccess=()=>{const c=req.result;if(!c){rows.forEach(validate);resolve({items:clone(rows),nextCursor:more?btoa(JSON.stringify({v:1,owner,after:rows.at(-1).id})):null});return;}
        if(c.primaryKey>after){if(rows.length===limit){more=true;rows.forEach(validate);resolve({items:clone(rows),nextCursor:btoa(JSON.stringify({v:1,owner,after:rows.at(-1).id}))});return;} rows.push(c.value);}
        c.continue();
      };req.onerror=()=>reject(req.error);
    });}finally{db.close();}
  }
  async function acquireLease(ownerValue,operationValue,{ttlMs=30000}={}) {
    const owner=uuid(ownerValue,"owner ID"),op=uuid(operationValue,"operation ID");
    if(!Number.isInteger(ttlMs)||ttlMs<1000||ttlMs>120000)fail("Lease duration must be 1–120 seconds.");
    let result=null;
    await transaction("readwrite",(store,tx)=>{
      const req=store.get(key(owner,op));
      req.onsuccess=()=>{const r=req.result;if(!r||r.ownerId!==owner){tx.abort();return;}
        validate(r);const time=Date.now();
        if(r.lease && Date.parse(r.lease.expiresAt)>time){tx.abort();return;}
        r.leaseEpoch+=1;r.lease={token:crypto.randomUUID(),epoch:r.leaseEpoch,expiresAt:new Date(time+ttlMs).toISOString()};
        r.revision+=1;r.updatedAt=now();validate(r);result=clone(r.lease);store.put(r);
      };
    });
    if(!result)fail("Operation is leased by another tab or unavailable.");
    return result;
  }
  async function renewLease(ownerValue,operationValue,lease,{ttlMs=60000}={}) {
    const owner=uuid(ownerValue,"owner ID"),op=uuid(operationValue,"operation ID");
    if(!Number.isInteger(ttlMs)||ttlMs<1000||ttlMs>120000)fail("Lease duration must be 1–120 seconds.");
    let renewed=null;
    await transaction("readwrite",(store,tx)=>{
      const req=store.get(key(owner,op));
      req.onsuccess=()=>{const r=req.result;if(!r||r.ownerId!==owner||!r.lease||r.lease.token!==lease?.token||r.lease.epoch!==lease?.epoch||r.leaseEpoch!==lease.epoch){tx.abort();return;}
        validate(r);const time=Date.now();
        if(Date.parse(r.lease.expiresAt)<=time){tx.abort();return;}
        r.lease.expiresAt=new Date(time+ttlMs).toISOString();
        validate(r);renewed=clone(r.lease);store.put(r);
      };
    });
    if(!renewed)fail("Lease renewal rejected: lease is stale, expired, or no longer owned.");
    return renewed;
  }
  async function checkpoint(input) {
    const owner=uuid(input?.ownerId,"owner ID"),op=uuid(input?.operationId,"operation ID");
    const token=str(input?.leaseToken,"lease token",128),epoch=input?.leaseEpoch;
    let updated=null;
    await transaction("readwrite",(store,tx)=>{
      const req=store.get(key(owner,op));
      req.onsuccess=()=>{const r=req.result;if(!r||r.ownerId!==owner){tx.abort();return;}
        validate(r);
        if(!r.lease||r.lease.token!==token||r.lease.epoch!==epoch||r.leaseEpoch!==epoch||Date.parse(r.lease.expiresAt)<=Date.now()){tx.abort();return;}
        if(input.expectedRevision!==r.revision){tx.abort();return;}
        const next=str(input.state,"next state",40);
        if(next!==r.state && !(NEXT[r.state]||[]).includes(next)){tx.abort();return;}
        if(input.page!==undefined){
          const p=input.page;if(!p||!Number.isInteger(p.count)||p.count<r.page.count||p.count>10000) {tx.abort();return;}
          if(p.cursor!==null && (typeof p.cursor!=="string"||p.cursor.length>512)){tx.abort();return;}
          if(p.digest!==null && !/^[a-f0-9]{64}$/i.test(p.digest)){tx.abort();return;}
          r.page=clone(p);
        }
        if(input.references!==undefined)r.references=clone(input.references);
        if(input.activation!==undefined)r.activation=clone(input.activation);
        r.state=next;r.revision+=1;r.updatedAt=now();validate(r);store.put(r);updated=clone(r);
      };
    });
    if(!updated)fail("Checkpoint rejected: stale lease, revision, owner, or illegal state transition.");
    return updated;
  }
  async function releaseLease(ownerValue,operationValue,lease) {
    const owner=uuid(ownerValue,"owner ID"),op=uuid(operationValue,"operation ID");
    let released=false;
    await transaction("readwrite",(store,tx)=>{
      const req=store.get(key(owner,op));
      req.onsuccess=()=>{const r=req.result;if(!r||!r.lease||r.lease.token!==lease?.token||r.lease.epoch!==lease?.epoch||r.leaseEpoch!==lease.epoch){tx.abort();return;}
        r.lease=null;r.revision+=1;r.updatedAt=now();store.put(r);released=true;
      };
    });
    if(!released)fail("Lease release rejected: lease is stale or no longer owned.");
    return true;
  }
  globalThis.PWACharacterRestoreJournal=Object.freeze({protocolVersion:PROTOCOL,create,get,listPage,acquireLease,renewLease,checkpoint,releaseLease});
})();
