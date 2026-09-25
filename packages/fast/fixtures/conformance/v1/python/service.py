from typing import overload

class Account:
    def __init__(self, account_id: str) -> None:
        self.id = account_id

@overload
def resolve(value: str) -> Account: ...

@overload
def resolve(value: int) -> Account: ...

def resolve(value: str | int) -> Account:
    return Account(str(value))

def exercise() -> Account:
    return resolve('acct-1')
