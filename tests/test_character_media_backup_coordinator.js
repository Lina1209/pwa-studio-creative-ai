"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { webcrypto } = require("node:crypto");

const source = fs.readFileSync("character-media-backup-coordinator.js", "utf8");
const sandbox = { crypto: webcrypto, Blob };
sandbox.globalThis = sandbox;
vm.runInNewContext(source, sandbox, { filename: "character-media-backup-coordinator.js" });
const coordinator = sandbox.PWACharacterMediaBackupCoordinator;
const owner = "11111111-1111-4111-8111-111111111111";
const localCharacter = "22222222-2222-4222-8222-222222222222";
const cloudCharacter = "33333333-3333-4333-8333-333333333333";
const reference = "44444444-4444-4444-8444-444444444444";
const asset = "55555555-5555-4555-8555-555555555555";
const blob = new Blob(["image-bytes"], { type: "image/png" });
const localItems = [{ id: localCharacter, referenceImages: [{ id: reference, name: "face.png" }] }];
const cloudByLocalId = new Map([[localCharacter, { id: cloudCharacter, source_local_id: localCharacter }]]);
const digest = async value => Buffer.from(await webcrypto.subtle.digest("SHA-256", await value.arrayBuffer())).toString("hex");

function transfer(overrides = {}) {
  const calls = [];
  return {
    calls,
    async uploadAsset(input) {
      calls.push(["upload", input]);
      return {
        assetId: asset, characterId: cloudCharacter, localReferenceId: reference,
        sha256: await digest(blob), sizeBytes: blob.size, mimeType: blob.type,
        ...overrides.upload
      };
    },
    async waitForReady(input) {
      calls.push(["ready", input]);
      return {
        assetId: asset, characterId: cloudCharacter, localReferenceId: reference,
        sha256: await digest(blob), sizeBytes: blob.size, mimeType: blob.type, status: "ready",
        ...overrides.ready
      };
    }
  };
}

(async () => {
  const good = transfer();
  const result = await coordinator.backupCharacterMedia({
    ownerId: owner, localItems, cloudByLocalId, getLocalBlob: async (id, ownerId) => {
      assert.equal(id, reference); assert.equal(ownerId, owner); return blob;
    }, mediaTransfer: good, isCurrent: () => true
  });
  assert.equal(result.uploadedAndVerified, 1);
  assert.equal(result.results[0].cloudAssetId, asset);
  assert.deepEqual(good.calls.map(x => x[0]), ["upload", "ready"]);
  console.log("PASS uploads local Blob and waits for exact cloud ready verification");

  let uploadCalls = 0, current = true;
  await assert.rejects(() => coordinator.backupCharacterMedia({
    ownerId: owner, localItems, cloudByLocalId,
    getLocalBlob: async () => { current = false; return blob; },
    mediaTransfer: { async uploadAsset() { uploadCalls++; }, async waitForReady() {} },
    isCurrent: () => current
  }), /Account changed/);
  assert.equal(uploadCalls, 0);
  console.log("PASS account switch after local read prevents cloud upload");

  let missingUploadCalls = 0;
  await assert.rejects(() => coordinator.backupCharacterMedia({
    ownerId: owner, localItems, cloudByLocalId, getLocalBlob: async () => null,
    mediaTransfer: { async uploadAsset() { missingUploadCalls++; }, async waitForReady() {} },
    isCurrent: () => true
  }), /Blob is missing/);
  assert.equal(missingUploadCalls, 0);
  console.log("PASS missing or foreign-owner Blob fails closed before upload");

  const wrongAck = transfer({ upload: { sha256: "0".repeat(64) } });
  await assert.rejects(() => coordinator.backupCharacterMedia({
    ownerId: owner, localItems, cloudByLocalId, getLocalBlob: async () => blob,
    mediaTransfer: wrongAck, isCurrent: () => true
  }), /acknowledgement does not match/);
  assert.equal(wrongAck.calls.length, 1);
  console.log("PASS mismatched upload acknowledgement is rejected before readiness polling");

  const notReady = transfer({ ready: { status: "object_uploaded" } });
  await assert.rejects(() => coordinator.backupCharacterMedia({
    ownerId: owner, localItems, cloudByLocalId, getLocalBlob: async () => blob,
    mediaTransfer: notReady, isCurrent: () => true
  }), /did not reach the exact verified ready state/);
  console.log("PASS non-ready cloud asset is never reported as backed up");

  await assert.rejects(() => coordinator.backupCharacterMedia({
    ownerId: owner, localItems,
    cloudByLocalId: new Map([[localCharacter, { id: cloudCharacter, source_local_id: "66666666-6666-4666-8666-666666666666" }]]),
    getLocalBlob: async () => blob, mediaTransfer: transfer(), isCurrent: () => true
  }), /mapping is missing or does not match/);
  console.log("PASS cloud/local character identity mismatch is rejected");

  const noRefs = await coordinator.backupCharacterMedia({
    ownerId: owner, localItems: [{ id: localCharacter, referenceImages: [] }],
    cloudByLocalId, getLocalBlob: async () => null, mediaTransfer: transfer(), isCurrent: () => true
  });
  assert.equal(noRefs.uploadedAndVerified, 0);
  assert.equal(noRefs.skippedWithoutLocalReferences, 1);
  console.log("PASS empty reference list is a safe no-op");

  console.log("All character media backup coordinator tests passed.");
})().catch(error => { console.error(error); process.exitCode = 1; });
