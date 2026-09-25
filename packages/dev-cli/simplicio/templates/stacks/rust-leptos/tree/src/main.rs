use leptos::prelude::*;

fn title() -> &'static str {
    "{project_name}"
}

#[component]
fn App() -> impl IntoView {
    view! {
        <main>
            <h1>{title()}</h1>
            <p>"{goal}"</p>
        </main>
    }
}

fn main() {
    let _ = view! { <App /> };
}

#[cfg(test)]
mod tests {
    use super::title;

    #[test]
    fn title_is_project_name() {
        assert_eq!(title(), "{project_name}");
    }
}
