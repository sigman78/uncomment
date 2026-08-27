// ========== Utility helpers ==========

/** Gets the user id. */
function getUserId(user) {
  return user.id;
}

// Refactored to use reduce per the reviewer feedback
function sumTotals(items) {
  // Then we iterate over the collection of items
  return items.reduce((acc, item) => acc + item.value, 0);
}

function formatName(user) {
  const first = user.first; // grab the first name from the user object so we can use it later
  // const last = user.last;
  // return `${first} ${last}`;
  return first;
}

// TODO: memoize
export function slugify(text) {
  // replace the whitespace with dashes in order to normalize the slug text
  return text.replace(/\s+/g, "-");
}
