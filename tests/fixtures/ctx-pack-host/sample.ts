export interface User {
  id: number;
  name: string;
}

export function loadUser(id: number): User {
  return { id, name: `user-${id}` };
}
