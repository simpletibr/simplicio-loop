"""Check that PR coverage matches issue criteria."""
from __future__ import annotations

import re
import unicodedata
from typing import Mapping, Sequence

from .diffs import FileChange
from .model import CheckResult, PASS, FAIL, SKIPPED


# Stopwords in Portuguese and English
_STOPWORDS_PT = {
    "a", "ao", "aos", "aquela", "aquelas", "aquele", "aqueles", "aquilo",
    "as", "até", "através", "cada", "coisa", "coisas", "com", "como",
    "da", "das", "de", "dela", "delas", "dele", "deles", "demais",
    "dentro", "depois", "desde", "dessa", "desse", "desta", "deste",
    "deve", "devem", "devia", "deviam", "devíamos", "devêssemos",
    "devíssemos", "devríamos", "devêssemos", "devo", "devs", "devês",
    "devíamos", "devêssemos", "devíssemos", "devríamos", "devêssemos",
    "devemos", "deveria", "deveriam", "deverei", "devereis", "deveremos",
    "deveria", "deveriam", "deveríamos", "deveríeis", "deveria",
    "deveres", "deveria", "deveriam", "deveria", "deveria",
    "di", "dia", "dias", "diante", "didática", "diferente", "diferentes",
    "digo", "dinheiro", "diz", "dizer", "dizem", "do", "dos", "doze",
    "durante", "e", "é", "em", "embora", "embuça", "eminência",
    "encima", "encontra", "encontradas", "encontrado", "encontrados",
    "encontram", "encontramos", "encontran", "encontrapelo", "encontraramse",
    "encontrara", "encontrará", "encontravam", "encontravamos", "encontrem",
    "encontro", "ainda", "além", "ambas", "ambos", "amo", "antes", "apenas",
    "apesar", "aproximadamente", "aquela", "aquelas", "aquele", "aqueles",
    "aquilo", "ardei", "ardemos", "arde", "ardem", "ardente", "ardentemente",
    "arder", "arderia", "arderíamos", "arderes", "arderia", "arderíeis",
    "arderia", "arderei", "ardereis", "arderemos", "arderia", "arderíamos",
    "arderíeis", "arderia", "arderem", "ardessem", "ardessemos", "ardeste",
    "ardesteis", "arde", "ardem", "ardente", "ardentemente", "arder",
    "arderia", "arderíamos", "arderes", "arderia", "arderíeis", "arderia",
    "arderei", "ardereis", "arderemos", "arderia", "arderíamos", "arderíeis",
    "arderia", "arderem", "ardessem", "ardessemos", "ardeste", "ardesteis",
    "arde", "ardem", "ardente", "ardentemente", "arder", "arderia",
    "arderíamos", "arderes", "arderia", "arderíeis", "arderia", "arderei",
    "ardereis", "arderemos", "arderia", "arderíamos", "arderíeis", "arderia",
    "arderem", "ardessem", "ardessemos", "ardeste", "ardesteis",
    # English stopwords
    "a", "about", "above", "after", "again", "against", "all", "am", "an",
    "and", "any", "are", "as", "at", "be", "because", "been", "before",
    "being", "below", "between", "both", "by", "can", "could", "did", "do",
    "does", "doing", "down", "during", "each", "few", "for", "from", "had",
    "has", "have", "having", "he", "her", "here", "hers", "herself", "him",
    "himself", "his", "how", "i", "if", "in", "into", "is", "it", "its",
    "itself", "just", "me", "might", "more", "most", "my", "myself", "no",
    "nor", "not", "of", "off", "on", "or", "other", "our", "ours", "ourselves",
    "out", "over", "own", "same", "she", "should", "so", "some", "such",
    "than", "that", "the", "their", "theirs", "them", "themselves", "then",
    "there", "these", "they", "this", "those", "through", "to", "too",
    "under", "until", "up", "very", "was", "we", "were", "what", "when",
    "where", "which", "while", "who", "whom", "why", "will", "with", "you",
    "your", "yours", "yourself", "yourselves",
}


def criteria(issue_body: str) -> list[str]:
    """Extract unchecked criteria from issue body.

    Returns a list of criterion texts (the part after "- [ ]").
    """
    result = []
    for line in issue_body.splitlines():
        if match := re.match(r"^\s*-\s*\[\s*\]\s*(.+)$", line):
            result.append(match.group(1).strip())
    return result


def closes(pr_body: str, issue: int) -> bool:
    """Check if PR body closes the given issue.

    Recognizes: close/closes/closed, fix/fixes/fixed, resolve/resolves/resolved
    (case-insensitive), and PT-BR: fecha/fechar/fechado, resolvido/resolver/resolvida.
    Accepts "owner/repo#N" format.

    Does NOT close on "Parte de #N" (which indicates a partial PR).
    """
    # "Parte de" means partial, so it doesn't close
    if re.search(r"Parte\s+de\s+#\d+", pr_body, re.IGNORECASE):
        return False

    # Check for closing keywords
    pattern = r"(?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved|fecha|fechar|fechado|resolvido|resolvida)\s*:?\s+(?:(?:\w+/\w+)?#)?(\d+)"
    match = re.search(pattern, pr_body, re.IGNORECASE)
    return match and int(match.group(1)) == issue


def check_coverage(
    issue: int | None,
    issue_body: str,
    changes: Sequence[FileChange],
    added_text: Mapping[str, str],
    pr_body: str,
) -> CheckResult:
    """Verify PR coverage matches issue criteria.

    Args:
        issue: Issue number, or None if no issue.
        issue_body: Body of the issue.
        changes: File changes from the PR.
        added_text: Mapping of path -> text of added lines.
        pr_body: Body of the PR.

    Returns:
        CheckResult with status PASS/FAIL/SKIPPED.
    """
    if issue is None:
        return CheckResult("coverage", SKIPPED, ("PR sem issue",))

    crit = criteria(issue_body)
    if not crit:
        return CheckResult("coverage", SKIPPED, ("issue sem criterios",))

    # Check which criteria are covered
    covered: list[str] = []
    uncovered: list[str] = []

    for crit_text in crit:
        if _is_criterion_covered(crit_text, changes, added_text):
            covered.append(crit_text)
        else:
            uncovered.append(crit_text)

    if not uncovered:
        # All covered -> PASS
        return CheckResult("coverage", PASS, measured={
            "criteria": len(crit),
            "covered": len(covered),
            "uncovered": [],
            "partial": False,
            "evidence": {c: [] for c in covered},
        })

    # Some uncovered: check for partial
    is_partial_pr = bool(re.search(r"Parte\s+de\s+#\d+", pr_body, re.IGNORECASE))
    closes_issue = closes(pr_body, issue)

    if is_partial_pr:
        # Check if it has falta list
        falta_match = re.search(r"(?:Falta|Faltando|Pendente|Pendentes|Missing)\s*:\s*(.*?)(?=\n\n|\Z)", pr_body, re.IGNORECASE | re.DOTALL)
        if not falta_match:
            return CheckResult("coverage", FAIL, (
                "PR parcial sem lista do que falta",
            ))

        falta_text = falta_match.group(1)
        falta_items = re.findall(r"^\s*-\s*\[\s*\]", falta_text, re.MULTILINE)
        if len(falta_items) < len(uncovered):
            return CheckResult("coverage", FAIL, (
                f"lista 'Falta' tem {len(falta_items)} items mas ha {len(uncovered)} criterios descobertos",
            ))

        # Partial PR with proper falta list is PASS
        return CheckResult("coverage", PASS, measured={
            "criteria": len(crit),
            "covered": len(covered),
            "uncovered": uncovered,
            "partial": True,
            "evidence": {c: [] for c in covered},
        })

    if closes_issue:
        return CheckResult("coverage", FAIL, (
            f"PR parcial sem 'Parte de #' ou com palavra de fechamento",
        ))

    # Not partial, not closed -> FAIL with detailed reasons
    reasons = []
    for uncov in uncovered:
        reasons.append(f"criterio sem cobertura: {uncov}")

    return CheckResult("coverage", FAIL, tuple(reasons), measured={
        "criteria": len(crit),
        "covered": len(covered),
        "uncovered": uncovered,
        "partial": False,
        "evidence": {},
    })


def _is_criterion_covered(
    criterion: str,
    changes: Sequence[FileChange],
    added_text: Mapping[str, str],
) -> bool:
    """Check if a criterion is covered by the PR changes."""
    # Build haystack
    all_paths = " ".join(ch.path for ch in changes)
    all_added_text = " ".join(added_text.values())
    haystack = f"{all_paths} {all_added_text}"

    # Extract tokens from criterion
    tokens = _extract_tokens(criterion)

    # Check for file path tokens (backtick-enclosed or with / or .py/.md/.json/.toml)
    file_tokens = [t for t in tokens if "/" in t or t.endswith((".py", ".md", ".json", ".toml", ".yml"))]
    for ft in file_tokens:
        for change in changes:
            if ft in change.path or change.path.endswith(ft):
                return True

    # Check for identifier tokens (snake_case or CamelCase)
    identifier_tokens = [t for t in tokens if "_" in t or any(c.isupper() for c in t)]
    for it in identifier_tokens:
        if _word_in_text(it, haystack):
            return True

    # Check for significant words (>= 5 letters, no accents, lowercase)
    words = _extract_significant_words(criterion)
    if words:
        # Count how many match
        matched = sum(1 for w in words if _word_matches_haystack(w, haystack))
        # If exactly 1 word: it must match; if 2+: need >= 50%
        if len(words) == 1:
            if matched > 0:
                return True
        else:
            # Need at least 50% match
            threshold = (len(words) + 1) // 2
            if matched >= threshold:
                return True

    # Also check if the whole criterion (minus stopwords) can be inferred from path/text
    # e.g., "add tests" -> "tests" should be in paths
    non_stop_tokens = [t for t in criterion.split() if t.lower() not in _STOPWORDS_PT]
    if non_stop_tokens and all(_word_matches_haystack(t.lower(), haystack) for t in non_stop_tokens):
        return True

    return False


def _extract_tokens(text: str) -> list[str]:
    """Extract tokens from criterion text.

    Includes:
    - Backtick-enclosed strings
    - Paths (containing /)
    - File extensions (.py, .md, .json, .toml, .yml)
    - Snake_case and CamelCase identifiers
    """
    tokens: list[str] = []

    # Backtick-enclosed
    tokens.extend(re.findall(r"`([^`]+)`", text))

    # Paths and file extensions
    tokens.extend(re.findall(r"\b[\w\-./]+(?:\.(?:py|md|json|toml|yml|txt|rst))\b", text))

    # Snake_case identifiers
    tokens.extend(re.findall(r"\b[a-z][a-z0-9]*_[a-z0-9_]*\b", text))

    # CamelCase identifiers
    tokens.extend(re.findall(r"\b[A-Z][a-z0-9]*(?:[A-Z][a-z0-9]*)+\b", text))

    return [t.lower() for t in tokens]


def _extract_significant_words(text: str) -> list[str]:
    """Extract significant words (>= 5 letters, no accents, not stopwords)."""
    # Remove accents
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")

    words: list[str] = []
    for word in re.findall(r"\b[a-z]+\b", text.lower()):
        if len(word) >= 5 and word not in _STOPWORDS_PT:
            words.append(word)
    return words


def _word_in_text(word: str, text: str) -> bool:
    """Check if a word appears as a whole word in text (with word boundaries)."""
    # Normalize both
    word_norm = "".join(c for c in unicodedata.normalize("NFD", word) if unicodedata.category(c) != "Mn")
    text_norm = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")

    pattern = r"\b" + re.escape(word_norm) + r"\b"
    return bool(re.search(pattern, text_norm, re.IGNORECASE))


def _word_matches_haystack(word: str, text: str) -> bool:
    """Check if a word appears in text as: exact word, prefix, suffix, or shared stem."""
    # Normalize both
    word_norm = "".join(c for c in unicodedata.normalize("NFD", word) if unicodedata.category(c) != "Mn")
    text_norm = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")

    # Check for exact word match
    pattern = r"\b" + re.escape(word_norm) + r"\b"
    if re.search(pattern, text_norm, re.IGNORECASE):
        return True

    # Check for prefix match (word is prefix of another word)
    pattern = r"\b" + re.escape(word_norm) + r"[a-z]*\b"
    if re.search(pattern, text_norm, re.IGNORECASE):
        return True

    # Check for suffix match (word is suffix of another word)
    pattern = r"\b[a-z]*" + re.escape(word_norm) + r"\b"
    if re.search(pattern, text_norm, re.IGNORECASE):
        return True

    # Check for shared stem (first 6 characters match)
    if len(word_norm) >= 6:
        stem = word_norm[:6]
        if re.search(r"\b[a-z]*" + re.escape(stem), text_norm, re.IGNORECASE):
            return True

    return False
