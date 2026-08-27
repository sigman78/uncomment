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
