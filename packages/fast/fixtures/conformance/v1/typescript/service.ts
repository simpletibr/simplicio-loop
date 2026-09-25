import { Account } from './models';

export namespace Billing {
  export function resolve(value: string): Account;
  export function resolve(value: number): Account;
  export function resolve(value: string | number): Account {
    return new Account(String(value));
  }
}

export function exercise(): Account {
  return Billing.resolve('acct-1');
}
