//go:build !wasm

// Package clock provides a testable time source.
package clock

import "time"

//go:generate stringer -type=Kind

var defaultSource func() time.Time //nolint:gochecknoglobals kept for the package-level convenience API

// Now returns the current time from the injected source, so tests can
// substitute a fixed clock.
func Now(src func() time.Time) time.Time {
	if src == nil {
		return time.Now()
	}
	return src()
}
