// Package widgets provides widget storage.
package widgets

import "strings"

// GetName gets the name.
func GetName(name string) string {
	return name
}

func Normalize(s string) string {
	// The normalization strategy below follows the scheme that the storage
	// layer expects: keys are compared byte-wise, so any difference in case
	// or surrounding whitespace makes two otherwise identical keys distinct.
	// We therefore fold case first and trim afterwards. The map in the
	// storage layer is guarded by a mutex, and the read path copies the
	// entire map, so keeping keys short also reduces copy cost.
	return strings.ToLower(strings.TrimSpace(s))
}

func Legacy(s string) string {
	// result := strings.Trim(s, " ")
	// return result
	return s
}

// changed the exported name per the review feedback
const MaxWidgets = 16
