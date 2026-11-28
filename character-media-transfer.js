/* Authenticated, owner-fenced character media transfer adapter.
 * Network and UI remain injected; this module never mutates local library metadata.
 */
(() => {
  "use strict";
  const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const MIME=new Set(["image/png","image/jpeg","image/webp"]),MAX_BYTES=8*1024*1024;
  const fail=message=>{throw new Error(message);};
  const hex=bytes=>Array.from(new Uint8Array(bytes),x=>x.toString(16).padStart(2,"0")).join("");
  const sha256=async value=>hex(await crypto.subtle.digest("SHA-256",value instanceof Blob?await value.arrayBuffer():new TextEncoder().encode(value)));
  function createCharacterMediaTransferAdapter({fetchImpl=globalThis.fetch,apiBase,getAccessToken,getOwnerId,getContextVersion,isCurrent}={}){
    if(typeof fetchImpl!=="function"||typeof getAccessToken!=="function"||typeof getOwnerId!=="function"||typeof getContextVersion!=="function"||typeof isCurrent!=="function")fail("Character media transfer dependencies are incomplete.");
    const base=String(apiBase||"").replace(/\/+$/,"");
    if(!/^https:\/\//i.test(base)&&!/^http:\/\/localhost(?::\d+)?$/i.test(base)&&!/^http:\/\/127\.0\.0\.1(?::\d+)?$/i.test(base))fail("A valid HTTPS API base is required.");
    const capture=()=>{const ownerId=getOwnerId(),contextVersion=getContextVersion(),token=getAccessToken();if(typeof ownerId!=="string"||!UUID.test(ownerId)||typeof token!=="string"||!token)fail("An authenticated account is required for media transfer.");if(!isCurrent(ownerId,contextVersion))fail("Account is not current.");return {ownerId,contextVersion,token};};
    const assertCurrent=ctx=>{if(!isCurrent(ctx.ownerId,ctx.contextVersion)||getOwnerId()!==ctx.ownerId)fail("Account changed during media transfer.");};
    const request=async(path,init,ctx)=>{assertCurrent(ctx);const response=await fetchImpl(base+path,{...init,headers:{Authorization:"Bearer "+ctx.token,...(init?.headers||{})},cache:"no-store",credentials:"omit"});assertCurrent(ctx);return response;};
    const downloadAsset=async({cloudAssetId,expectedSha256,expectedSizeBytes,expectedMimeType})=>{
      const ctx=capture();
      if(typeof cloudAssetId!=="string"||!UUID.test(cloudAssetId)||!/^[a-f0-9]{64}$/i.test(expectedSha256||"")||!Number.isSafeInteger(expectedSizeBytes)||expectedSizeBytes<1||expectedSizeBytes>MAX_BYTES||!MIME.has(expectedMimeType))fail("Cloud image descriptor is invalid.");
      const response=await request("/api/media/"+encodeURIComponent(cloudAssetId)+"/content",{method:"GET"},ctx);
      if(!response.ok)fail("Cloud image could not be downloaded (HTTP "+response.status+").");
      const type=(response.headers.get("Content-Type")||"").split(";")[0].trim().toLowerCase(),serverDigest=(response.headers.get("X-Content-SHA256")||"").toLowerCase();
      if(type!==expectedMimeType||serverDigest!==expectedSha256.toLowerCase())fail("Cloud image response headers do not match the reviewed manifest.");
      const blob=await response.blob();assertCurrent(ctx);
      if(blob.size!==expectedSizeBytes||blob.size>MAX_BYTES||blob.type!==expectedMimeType)fail("Downloaded image size or MIME type is invalid.");
      if((await sha256(blob))!==expectedSha256.toLowerCase())fail("Downloaded image SHA-256 verification failed.");
      return blob;
    };
    const uploadAsset=async({characterId,localReferenceId,fileName,blob})=>{
      const ctx=capture();
      if(typeof characterId!=="string"||!UUID.test(characterId)||typeof localReferenceId!=="string"||!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(-[a-z0-9_-]{8,80})?$/i.test(localReferenceId)||!(blob instanceof Blob)||blob.size<1||blob.size>MAX_BYTES||!MIME.has(blob.type)||typeof fileName!=="string"||!fileName.trim()||fileName.length>255)fail("Local image upload descriptor is invalid.");
      const digest=await sha256(blob);assertCurrent(ctx);
      const idempotencyKey=(await sha256([ctx.ownerId,characterId,localReferenceId,digest].join(":"))).slice(0,64);
      const form=new FormData();form.append("file",blob,fileName);form.append("local_reference_id",localReferenceId);
      const response=await request("/api/characters/"+encodeURIComponent(characterId)+"/references",{method:"POST",headers:{"Idempotency-Key":idempotencyKey},body:form},ctx);
      if(!response.ok)fail("Image upload was not accepted (HTTP "+response.status+").");
      let data;try{data=await response.json();}catch{fail("Image upload response is invalid.");}assertCurrent(ctx);
      const asset=data?.asset;
      if(!asset||!UUID.test(asset.id||"")||asset.character_id!==characterId||asset.local_reference_id!==localReferenceId||asset.file_type!==blob.type||asset.size_bytes!==blob.size||!["pending_upload","object_uploaded","ready"].includes(asset.status)||!["pending","complete"].includes(data.verification))fail("Server did not confirm the exact uploaded image.");
      return Object.freeze({assetId:asset.id,characterId,localReferenceId,status:asset.status,verification:data.verification,sha256:digest,sizeBytes:blob.size,mimeType:blob.type});
    };
    return Object.freeze({downloadAsset,uploadAsset});
  }
  globalThis.PWACharacterMediaTransfer=Object.freeze({createCharacterMediaTransferAdapter});
})();
