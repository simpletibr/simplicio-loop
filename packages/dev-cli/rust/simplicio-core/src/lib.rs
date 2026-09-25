//! Rust hot-path implementations exposed to Python via PyO3.
//!
//! Issue #17 ships the build scaffold and a smoke function (`hello`).
//! Issue #18 ships `build_6layer_prompt`: a single-pass, allocation-aware
//! substitution + comment-strip over the simplicio 6-layer template. It's
//! the equivalent of the Python `build_prompt` *after* the upstream blocks
//! (precedent / skill / target context / adaptation) have already been
//! built — the Python side stays responsible for orchestration and for
//! anything that touches sentence-transformers, the file system, or the
//! mapper artifacts.

use bumpalo::Bump;
use pyo3::prelude::*;

/// Smoke function used by the test suite to confirm the Rust extension
/// loads and PyO3 string conversion works in both directions.
#[pyfunction]
fn hello(name: &str) -> String {
    format!("hello, {name}!")
}

/// Re-implementation of `simplicio.prompt.build_prompt` for the
/// substitution + comment-strip portion only. The arguments are already
/// the pre-built block contents (caller computes precedent, skill, etc.).
///
/// Layout:
///   1. allocate a bump arena sized to the template + ~25% for the
///      injected blocks (most replacements grow modestly)
///   2. walk the template once, emitting bytes into the output. When we
///      see `{{` and a known placeholder, push the matching value instead
///      of the placeholder; when we see `{#`, skip up to the matching
///      `#}` (the legacy regex stripped these as "comment" markers)
///   3. trim leading / trailing ASCII whitespace and return as String
///
/// We accept the placeholders as separate parameters (rather than a dict)
/// so PyO3 can borrow them directly without allocating a HashMap on the
/// Python heap; `bumpalo` is used for the small intermediate buffer of
/// `(placeholder, value)` pairs the matcher walks.
#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn build_6layer_prompt(
    template: &str,
    stack: &str,
    goal: &str,
    target: &str,
    precedent: &str,
    skill: &str,
    adaptation: &str,
    criteria: &str,
    constraints: &str,
) -> String {
    let arena = Bump::new();
    let pairs: bumpalo::collections::Vec<(&str, &str)> = bumpalo::vec![
        in &arena;
        ("{{STACK}}", stack),
        ("{{GOAL}}", goal),
        ("{{TARGET}}", target),
        ("{{PRECEDENT}}", precedent),
        ("{{SKILL}}", skill),
        ("{{ADAPTATION}}", adaptation),
        ("{{CRITERIA}}", criteria),
        ("{{CONSTRAINTS}}", constraints),
    ];
    let extra: usize = pairs.iter().map(|(_, v)| v.len().saturating_sub(8)).sum();
    let mut out = String::with_capacity(template.len() + extra);

    // Walk the template in UTF-8-safe string slices. At each step find the
    // earliest of `{{` (placeholder) or `{#` (comment open); emit the chunk
    // before it; then handle the token. Slicing only at byte indices that
    // came from `str::find` guarantees we never split a multibyte code point.
    let mut rest: &str = template;
    while !rest.is_empty() {
        let p_idx = rest.find("{{");
        let c_idx = rest.find("{#");
        let (idx, is_comment) = match (p_idx, c_idx) {
            (None, None) => {
                out.push_str(rest);
                break;
            }
            (Some(p), None) => (p, false),
            (None, Some(c)) => (c, true),
            (Some(p), Some(c)) if c < p => (c, true),
            (Some(p), _) => (p, false),
        };
        out.push_str(&rest[..idx]);
        rest = &rest[idx..];
        if is_comment {
            // skip up to the matching `#}`; if there is none, drop the rest
            match rest.find("#}") {
                Some(end) => rest = &rest[end + 2..],
                None => break,
            }
        } else {
            // try to match a known placeholder; otherwise emit `{{` literally
            match pairs.iter().find(|(pl, _)| rest.starts_with(*pl)) {
                Some((pl, val)) => {
                    out.push_str(val);
                    rest = &rest[pl.len()..];
                }
                None => {
                    out.push_str("{{");
                    rest = &rest[2..];
                }
            }
        }
    }

    out.trim().to_string()
}

#[pymodule]
fn simplicio_core(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(hello, m)?)?;
    m.add_function(wrap_pyfunction!(build_6layer_prompt, m)?)?;
    Ok(())
}
