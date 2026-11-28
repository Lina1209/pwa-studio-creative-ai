"use strict";
require("../character-media-transfer.js");
const assert=require("node:assert/strict");
const {webcrypto}=require("node:crypto");
if(!globalThis.crypto)globalThis.crypto=webcrypto;
const api=globalThis.PWACharacterMediaTransfer;
const owner="11111111-1111-4111-8111-111111111111";
const character="22222222-2222-4222-8222-222222222222";
const reference=character+"-33333333-3333-4333-8333-333333333333"; // Match the composite ID created by the Character Library UI.
const asset="44444444-4444-4444-8444-444444444444";
const bytes=new TextEncoder().encode("valid image fixture");
const blob=new Blob([bytes],{type:"image/png"});
const digest=async value=>Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",value instanceof Blob?await value.arrayBuffer():new TextEncoder().encode(value))),x=>x.toString(16).padStart(2,"0")).join("");
function harness(fetchImpl,isCurrent=()=>true){
 let context=7;
 const adapter=api.createCharacterMediaTransferAdapter({
  fetchImpl,apiBase:"https://api.example.test",getAccessToken:()=>"private-test-token",
  getOwnerId:()=>owner,getContextVersion:()=>context,isCurrent
 });
 return {adapter,setContext:value=>{context=value;}};
}
(async()=>{
 let calls=[];
 const uploadResponse=localReferenceId=>new Response(JSON.stringify({asset:{id:asset,character_id:character,local_reference_id:localReferenceId,file_type:"image/png",size_bytes:blob.size,status:"ready"},verification:"complete"}),{status:202,headers:{"Content-Type":"application/json"}});
 const h=harness(async(url,init)=>{calls.push({url,init});return uploadResponse(init.body.get("local_reference_id"));});
 const fallbackReference=character+"-"+Date.now().toString(36)+Math.random().toString(36).slice(2);
 const fallback=await h.adapter.uploadAsset({characterId:character,localReferenceId:fallbackReference,fileName:"fallback.png",blob});
 assert.equal(fallback.localReferenceId,fallbackReference,"legacy non-UUID suffix generated without crypto.randomUUID must remain accepted");
 const first=await h.adapter.uploadAsset({characterId:character,localReferenceId:reference,fileName:"reference.png",blob});
 const second=await h.adapter.uploadAsset({characterId:character,localReferenceId:reference,fileName:"reference.png",blob});
 assert.equal(first.assetId,asset);
 assert.equal(first.sha256,await digest(blob));
 assert.equal(calls[1].init.headers.Authorization,"Bearer private-test-token");
 assert.equal(calls[1].init.headers["Idempotency-Key"],calls[2].init.headers["Idempotency-Key"],"retry key must be stable for identical owner/card/reference/bytes");
 assert.ok(calls[1].init.body instanceof FormData);
 assert.equal(calls[1].init.body.get("local_reference_id"),reference);
 assert.equal(calls[1].init.body.get("file").size,blob.size);
 assert.equal(calls[1].init.headers["Content-Type"],undefined,"browser must set multipart boundary");
 let getCalls=0;
 const downloader=harness(async(url,init)=>{getCalls++;return new Response(blob,{status:200,headers:{"Content-Type":"image/png","X-Content-SHA256":await digest(blob)}});});
 const restored=await downloader.adapter.downloadAsset({cloudAssetId:asset,expectedSha256:await digest(blob),expectedSizeBytes:blob.size,expectedMimeType:"image/png"});
 assert.equal(await digest(restored),await digest(blob));
 assert.equal(getCalls,1);
 const readyDigest=await digest(blob);
 let statusCalls=0;
 const statusPoller=harness(async(url,init)=>{
  statusCalls++;
  assert.equal(url,"https://api.example.test/api/characters/"+character+"/references");
  assert.equal(init.method,"GET");
  const status=statusCalls===1?"object_uploaded":"ready";
  return new Response(JSON.stringify([{id:asset,character_id:character,local_reference_id:reference,status,size_bytes:blob.size,content_sha256:readyDigest,file_type:"image/png"}]),{status:200,headers:{"Content-Type":"application/json"}});
 });
 const verified=await statusPoller.adapter.waitForReady({characterId:character,assetId:asset,localReferenceId:reference,expectedSha256:readyDigest,expectedSizeBytes:blob.size,expectedMimeType:"image/png",timeoutMs:3000,pollIntervalMs:100});
 assert.equal(verified.status,"ready");
 assert.equal(verified.sha256,readyDigest);
 assert.equal(statusCalls,2,"readiness must be independently confirmed after object upload");
 const terminal=harness(async()=>new Response(JSON.stringify([{id:asset,character_id:character,local_reference_id:reference,status:"upload_failed",size_bytes:blob.size,content_sha256:readyDigest,file_type:"image/png"}]),{status:200}));
 await assert.rejects(()=>terminal.adapter.waitForReady({characterId:character,assetId:asset,localReferenceId:reference,expectedSha256:readyDigest,expectedSizeBytes:blob.size,expectedMimeType:"image/png",timeoutMs:1000,pollIntervalMs:100}),/did not reach a usable state/);
 const mismatched=harness(async()=>new Response(JSON.stringify([{id:asset,character_id:character,local_reference_id:reference,status:"ready",size_bytes:blob.size,content_sha256:"0".repeat(64),file_type:"image/png"}]),{status:200}));
 await assert.rejects(()=>mismatched.adapter.waitForReady({characterId:character,assetId:asset,localReferenceId:reference,expectedSha256:readyDigest,expectedSizeBytes:blob.size,expectedMimeType:"image/png",timeoutMs:1000,pollIntervalMs:100}),/does not match/);
 const badDigest=harness(async()=>new Response(blob,{status:200,headers:{"Content-Type":"image/png","X-Content-SHA256":"0".repeat(64)}}));
 const expectedDigest=await digest(blob);
 await assert.rejects(()=>badDigest.adapter.downloadAsset({cloudAssetId:asset,expectedSha256:expectedDigest,expectedSizeBytes:blob.size,expectedMimeType:"image/png"}),/headers/);
 let current=true;
 const fenced=harness(async(url,init)=>{current=false;return uploadResponse(init.body.get("local_reference_id"));},()=>current);
 await assert.rejects(()=>fenced.adapter.uploadAsset({characterId:character,localReferenceId:reference,fileName:"reference.png",blob}),/Account changed/);
 const invalid=harness(async(url,init)=>uploadResponse(init.body.get("local_reference_id")));
 await assert.rejects(()=>invalid.adapter.downloadAsset({cloudAssetId:"not-uuid",expectedSha256:"a".repeat(64),expectedSizeBytes:blob.size,expectedMimeType:"image/png"}),/descriptor/);
 console.log("PASS owner-fenced character media transfer: auth, stable idempotency, multipart upload, binary digest verification, invalid descriptor and account-switch fencing");
})().catch(error=>{console.error(error);process.exitCode=1;});
