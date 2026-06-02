export interface Greeting {
  audience: string;
  message: string;
}

export function greet(audience: string): Greeting {
  return { audience, message: `hello, ${audience}` };
}

export function farewell(audience: string): Greeting {
  return { audience, message: `bye, ${audience}` };
}
