"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const {create}=require("../movie-id.js");
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

test("uses native randomUUID when available",()=>{
 const expected="123e4567-e89b-42d3-a456-426614174000";
 assert.equal(create({randomUUID:()=>expected}),expected);
});
test("secure random fallback creates a UUID v4",()=>{
 const crypto={getRandomValues(bytes){bytes.fill(0);return bytes;}};
 assert.match(create(crypto),uuid);
});
test("non-crypto fallback still creates a UUID v4",()=>{
 const original=Math.random;
 try { Math.random=()=>0.5; assert.match(create(null),uuid); }
 finally { Math.random=original; }
});
