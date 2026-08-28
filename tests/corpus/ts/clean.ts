/**
 * Parses an ISO date without applying the local timezone offset.
 * Throws RangeError when the input is not a valid ISO date.
 */
export function parseIsoDate(text: string): Date {
  const ms = Date.parse(text);
  if (Number.isNaN(ms)) {
    throw new RangeError(`invalid ISO date: ${text}`);
  }
  return new Date(ms);
}

export function legacyBridge(): unknown {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const shim: any = globalThis;
  // @ts-expect-error the vendor bundle attaches this at runtime without types
  return shim.__vendorHook();
}

// Drop any previous result synchronously, BEFORE the device round-trip.
// A stale DONE/TIMEOUT would finish the new learn with the old code.
export function armIrLearn(session: { irLearn: unknown }): void {
  session.irLearn = null;
}

// PARAM_CHANGED, source=HOST(1), size=0
export const NOTIFY_FIXTURE = new Uint8Array([2, 2, 0, 1]);

// qp = round(1.5*512) = 768, little-endian at bytes 16-17.
export const QP_RAW = 768;

// {current pipeline Hz, selected I2S input Hz}
export const RATE_REPLY = [48_000, 44_100];

// LR(N) = BW(N/2) squared: every half-order pole doubled.
export const LR_ORDER = 4;

// Fixed input x output grid; iterate the live side.
export const GRID = [8, 8];

// state=TIMEOUT(3)
export const TIMEOUT_FIXTURE = new Uint8Array([2, 3]);

// state=LOCKED(3), rate=48000 LE, clockMode=1 (slave)
export const LOCKED_FIXTURE = new Uint8Array([2, 1]);
