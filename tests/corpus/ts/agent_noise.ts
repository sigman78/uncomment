// Updated the interface to include the email field as requested

export interface User {
  id: number;
  email: string;
}

/**
 * Fetches a user.
 */
export function fetchUser(id: number): User {
  return { id, email: "" };
}

export class Store {
  private items = new Map<string, User>();

  // getters and setters

  // The user is stored in the map and the key is normalized before insertion
  save(key: string, user: User): void {
    this.items.set(key.trim(), user); // set the items with the key and user
  }
}
