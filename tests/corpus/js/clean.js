// Debounce avoids one network call per keystroke; 250 ms feels instant.
export function debounce(fn, delay = 250) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

// Let's Encrypt rate-limits issuance, so renewals run once per day.
export function scheduleRenewal(run) {
  return setInterval(run, 24 * 60 * 60 * 1000);
}
