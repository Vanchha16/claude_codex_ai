// Display-only time formatting. Source data stays UTC; this never shifts stored or strategy timestamps.
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.VCTime = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  const cache = new Map();
  function formatter(tz) {
    const key = tz || "UTC";
    if (!cache.has(key)) {
      const opts = { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
        hourCycle: "h23", timeZoneName: "short" };
      if (key !== "local") opts.timeZone = key;
      cache.set(key, new Intl.DateTimeFormat("en-CA", opts));
    }
    return cache.get(key);
  }
  function toDate(value) {
    if (value === null || value === undefined || value === "") return null;
    if (typeof value === "number") return new Date(value * 1000); // UTC epoch seconds (chart time)
    const d = new Date(value); // ISO-8601 with Z from the API
    return isNaN(d.getTime()) ? null : d;
  }
  /** Format a UTC instant for display in `tz` ("UTC", "local" or an IANA zone such as "Asia/Bangkok"). */
  function format(value, tz, withSeconds) {
    const d = toDate(value);
    if (!d) return "—";
    const parts = Object.fromEntries(formatter(tz).formatToParts(d).map((p) => [p.type, p.value]));
    const time = withSeconds === false ? `${parts.hour}:${parts.minute}` : `${parts.hour}:${parts.minute}:${parts.second}`;
    return `${parts.year}-${parts.month}-${parts.day} ${time} ${tz === "UTC" ? "UTC" : parts.timeZoneName}`;
  }
  /** Short axis label for chart tick marks. */
  function axis(epochSeconds, tz, daily) {
    const d = toDate(epochSeconds);
    const parts = Object.fromEntries(formatter(tz).formatToParts(d).map((p) => [p.type, p.value]));
    return daily ? `${parts.month}-${parts.day}` : `${parts.hour}:${parts.minute}`;
  }
  return { format, axis, toDate };
});
