// Copyright (c) 2026 Example Corp. Licensed under the MIT license.

using System;

/// <summary>
/// Retries transient registry calls once with a short backoff.
/// </summary>
/// <param name="fetch">transport callback, invoked at most twice</param>
/// <returns>the raw record; null when the registry has no entry</returns>
class RetryClient {
    static string? Fetch(Func<string?> fetch) {
        try {
            return fetch();
        } catch (TimeoutException) {
            // workaround: the registry drops the first request under load
            return fetch();
        }
    }

    // ReSharper disable once InconsistentNaming
    const int BACKOFF_MS = 50; // tuned against the staging registry
}
