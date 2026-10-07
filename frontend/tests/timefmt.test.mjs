// node --test frontend/tests : display-timezone formatting never shifts the underlying UTC instant.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const VCTime = require("../../app/static/timefmt.js");

test("UTC display of an MT5 UTC epoch", () => {
  assert.equal(VCTime.format(1790762550, "UTC"), "2026-09-30 10:02:30 UTC");
  assert.equal(VCTime.format("2026-09-30T10:02:30Z", "UTC"), "2026-09-30 10:02:30 UTC");
});

test("Bangkok display is +7h without changing the instant", () => {
  const iso = "2026-09-30T10:02:30Z";
  const shown = VCTime.format(iso, "Asia/Bangkok");
  assert.match(shown, /^2026-09-30 17:02:30 (GMT\+7|ICT|UTC\+7)$/);
  assert.equal(VCTime.toDate(iso).toISOString(), "2026-09-30T10:02:30.000Z"); // source unchanged
});

test("day boundary crossing in Bangkok", () => {
  assert.match(VCTime.format("2026-09-30T20:00:00Z", "Asia/Bangkok"), /^2026-10-01 03:00:00 /);
  assert.equal(VCTime.axis(1790762550, "Asia/Bangkok", false), "17:02");
  assert.equal(VCTime.axis(1790762550, "UTC", true), "09-30");
});

test("missing values", () => {
  assert.equal(VCTime.format(null, "UTC"), "—");
  assert.equal(VCTime.format("not a date", "UTC"), "—");
});
