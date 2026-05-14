/** One observed HTTP round-trip (privacy-safe: path + status + timing only). */
export type ApiTrafficObservation = {
  method: string;
  pathPattern: string;
  status: number;
  durationMs?: number;
  /** Full URL without query, truncated */
  urlSample: string;
};
