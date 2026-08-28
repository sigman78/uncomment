// usings
using System;

// ============================================================
// Service implementation
// ============================================================
class GreetingService {
    /// <summary>Gets the greeting.</summary>
    string GetGreeting(string name) {
        // Now we build the greeting string from the name
        var text = "Hello, " + name;
        // Then we return the assembled greeting to the caller
        return text;
    }

    // var legacy = String.Format("Hello, {0}", name);
    // return legacy;
    int callCount = 0; // stores the number of times the greeting method has been called so far

    // TODO: add localization
    void Reset() {
        callCount = 0;
    }
}
