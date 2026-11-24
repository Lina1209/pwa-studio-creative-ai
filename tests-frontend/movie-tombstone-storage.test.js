"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const {read}=require("../movie-tombstone-storage.js");
const valid="123e4567-e89b-42d3-a456-426614174000";
const isUuid=value=>/^[0-9a-f-]{36}$/i.test(value);

test("missing deletion queue is an empty queue",()=>{
 assert.deepEqual(read({getItem:()=>null},"key",isUuid),[]);
});
test("valid deletion queue retains only valid UUID entries",()=>{
 assert.deepEqual(read({getItem:()=>JSON.stringify([valid,"bad",valid])},"key",isUuid),[valid,valid]);
});
test("unreadable deletion queue fails closed",()=>{
 assert.throws(()=>read({getItem:()=>{throw new Error("denied");}},"key",isUuid),/прочитать очередь/);
});
test("corrupt deletion queue is not treated as empty",()=>{
 assert.throws(()=>read({getItem:()=>"{"},"key",isUuid),/повреждена/);
});
test("non-array deletion queue is rejected",()=>{
 assert.throws(()=>read({getItem:()=>"{}"},"key",isUuid),/неверный формат/);
});
