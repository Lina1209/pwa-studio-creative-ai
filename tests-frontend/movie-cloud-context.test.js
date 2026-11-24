"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { capture, isCurrent } = require("../movie-cloud-context.js");

test("captures immutable owner and auth generation", () => {
  const context = capture("user-a", 4);
  assert.deepEqual(context, { ownerId: "user-a", authContextVersion: 4 });
  assert.equal(Object.isFrozen(context), true);
});

test("rejects an operation after account A switches to B", () => {
  const context = capture("user-a", 4);
  assert.equal(isCurrent(context, "user-b", 5), false);
});

test("rejects an old operation after same-user reauthentication", () => {
  const context = capture("user-a", 4);
  assert.equal(isCurrent(context, "user-a", 5), false);
});

test("accepts only the same owner and same auth generation", () => {
  const context = capture("user-a", 4);
  assert.equal(isCurrent(context, "user-a", 4), true);
  assert.equal(isCurrent(context, null, 4), false);
});

test("does not create a context for guest or invalid generation", () => {
  assert.equal(capture(null, 1), null);
  assert.equal(capture("user-a", NaN), null);
});

test("keeps only the newest pending account context", () => {
  const state = { pendingContext: null };
  const first = capture("user-a", 4);
  const latest = capture("user-b", 5);
  const { setPendingContext, takePendingContext } = require("../movie-cloud-context.js");
  setPendingContext(state, first);
  setPendingContext(state, latest);
  assert.equal(takePendingContext(state, context => isCurrent(context, "user-b", 5)), latest);
  assert.equal(state.pendingContext, null);
});

test("discards a stale pending context instead of replaying it", () => {
  const state = { pendingContext: capture("user-a", 4) };
  const { takePendingContext } = require("../movie-cloud-context.js");
  assert.equal(takePendingContext(state, context => isCurrent(context, "user-b", 5)), null);
  assert.equal(state.pendingContext, null);
});

test("distinguishes repeated loads for the same user across auth generations", () => {
  const firstLogin = capture("user-a", 8);
  const secondLogin = capture("user-a", 10);
  assert.equal(isCurrent(firstLogin, "user-a", 10), false);
  assert.equal(isCurrent(secondLogin, "user-a", 10), true);
});
