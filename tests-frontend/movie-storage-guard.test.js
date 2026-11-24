"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const {createMovieStorageGuard}=require("../movie-storage-guard.js");

test("local project writes are blocked after an unreadable project list",()=>{
 const guard=createMovieStorageGuard();
 assert.equal(guard.canWrite(),true);
 guard.readFailed();
 assert.equal(guard.canWrite(),false);
});

test("a successful later read re-enables local project writes",()=>{
 const guard=createMovieStorageGuard();
 guard.readFailed();
 guard.readSucceeded();
 assert.equal(guard.canWrite(),true);
});

test("browser app calls the exported storage guard factory",()=>{
 const source=fs.readFileSync(path.join(__dirname,"../app.js"),"utf8");
 assert.match(source,/PWAMovieStorageGuard\.createMovieStorageGuard\(\)/);
});
