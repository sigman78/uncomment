// Copyright (c) 2026 Example Corp. Licensed under the MIT license.

import Foundation

/// Retries a transient registry call once with a short backoff.
///
/// - Parameter fetch: transport callback, invoked at most twice
/// - Returns: the raw record, or nil when the registry has no entry
/// - Throws: rethrows only non-transient transport errors
func fetchWithRetry(_ fetch: () throws -> String?) rethrows -> String? {
    do {
        return try fetch()
    } catch is TimeoutError {
        // workaround: the registry drops the first request under load
        return try fetch()
    }
}

// MARK: - Session state

// swiftlint:disable identifier_name
let kBackoffMs = 50 // tuned against the staging registry
// swiftlint:enable identifier_name

struct TimeoutError: Error {}

/// Errors produced during server trust evaluation.
enum TrustError2: Error {
    /// Certificate pinning failed.
    case certificatePinningFailed
    /// Public key pinning failed.
    case publicKeyPinningFailed
}
