use anyhow::Result;
use clap::Parser;

#[derive(Parser)]
struct Args {
    #[arg(long, default_value = "world")]
    name: String,
}

fn greeting(name: &str) -> String {
    format!("hello {name}")
}

fn main() -> Result<()> {
    let args = Args::parse();
    println!("{}", greeting(&args.name));
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::greeting;

    #[test]
    fn greeting_uses_name() {
        assert_eq!(greeting("Simplicio"), "hello Simplicio");
    }
}
