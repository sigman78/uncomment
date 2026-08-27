import { useMemo } from "react";

// Memoized because the palette array would rebuild on every render otherwise.
export function usePalette(colors: string[]) {
  return useMemo(() => colors.map((c) => c.toUpperCase()), [colors]);
}
