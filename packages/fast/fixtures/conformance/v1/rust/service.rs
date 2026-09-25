mod models {
    pub struct Account {
        pub id: String,
    }
}

use models::Account;

pub fn resolve_text(value: &str) -> Account {
    Account { id: value.to_owned() }
}

pub fn resolve_number(value: u64) -> Account {
    resolve_text(&value.to_string())
}

#[cfg(test)]
mod tests {
    use super::resolve_text;

    #[test]
    fn resolves_account() {
        assert_eq!(resolve_text("acct-1").id, "acct-1");
    }
}
