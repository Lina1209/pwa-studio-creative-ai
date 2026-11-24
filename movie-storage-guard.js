"use strict";

const createMovieStorageGuard = () => {
  let lastReadFailed = false;
  return {
    readSucceeded() { lastReadFailed = false; },
    readFailed() { lastReadFailed = true; },
    canWrite() { return !lastReadFailed; }
  };
};

const api = { createMovieStorageGuard };
if (typeof module !== "undefined" && module.exports) module.exports = api;
if (typeof window !== "undefined") window.PWAMovieStorageGuard = api;
