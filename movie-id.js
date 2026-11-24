"use strict";

const createMovieId = cryptoObject => {
  if (cryptoObject && typeof cryptoObject.randomUUID === "function") return cryptoObject.randomUUID();
  const bytes = new Uint8Array(16);
  if (cryptoObject && typeof cryptoObject.getRandomValues === "function") cryptoObject.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map(value => value.toString(16).padStart(2, "0")).join("");
  return [hex.slice(0,8),hex.slice(8,12),hex.slice(12,16),hex.slice(16,20),hex.slice(20)].join("-");
};

const api = { create: createMovieId };
if (typeof module !== "undefined" && module.exports) module.exports = api;
if (typeof window !== "undefined") window.PWAMovieId = api;
