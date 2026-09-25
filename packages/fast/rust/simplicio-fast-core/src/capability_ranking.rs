use std::collections::BTreeSet;
use std::fmt;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

pub const FACT_SCHEMA: &str = "simplicio.fast.capability-fact/v1";
pub const CATALOG_SCHEMA: &str = "simplicio.fast.capability-catalog-projection/v1";
pub const MAX_CANDIDATES: usize = 100_000;
pub const MAX_RESULTS: usize = 10_000;

const TRUST_LEVELS: [(&str, i64); 5] = [
    ("untrusted", 0),
    ("derived_fact", 1),
    ("advisory", 2),
    ("verified", 3),
    ("authoritative", 4),
];

fn default_trust() -> String {
    "unknown".to_owned()
}

fn default_available() -> bool {
    true
}

fn default_scope() -> String {
    "*".to_owned()
}

fn default_metric_class() -> String {
    "unknown".to_owned()
}

fn default_health() -> String {
    "unknown".to_owned()
}

fn default_max_results() -> usize {
    32
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CapabilityRankingError {
    pub reason_code: String,
}

impl CapabilityRankingError {
    fn new(reason_code: &str) -> Self {
        Self {
            reason_code: reason_code.to_owned(),
        }
    }
}

impl fmt::Display for CapabilityRankingError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.reason_code)
    }
}

impl std::error::Error for CapabilityRankingError {}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct CapabilityCandidate {
    pub handle: String,
    pub kind: String,
    pub version: String,
    pub capabilities: Vec<String>,
    #[serde(default = "default_trust")]
    pub trust: String,
    #[serde(default = "default_available")]
    pub available: bool,
    #[serde(default)]
    pub estimated_cost: Option<i64>,
    #[serde(default)]
    pub estimated_latency_ms: Option<i64>,
    #[serde(default)]
    pub provenance: Vec<String>,
    #[serde(default)]
    pub policy_eligible: Option<bool>,
    #[serde(default = "default_scope")]
    pub scope: String,
    #[serde(default = "default_metric_class")]
    pub metric_class: String,
    #[serde(default)]
    pub freshness_seconds: Option<i64>,
    #[serde(default = "default_health")]
    pub health: String,
}

impl CapabilityCandidate {
    pub fn validate(&self) -> Result<(), CapabilityRankingError> {
        if [
            self.handle.as_str(),
            self.kind.as_str(),
            self.version.as_str(),
            self.trust.as_str(),
        ]
        .iter()
        .any(|value| value.trim().is_empty())
        {
            return Err(CapabilityRankingError::new("candidate_identity_invalid"));
        }
        if self
            .capabilities
            .iter()
            .any(|value| value.trim().is_empty())
        {
            return Err(CapabilityRankingError::new(
                "candidate_capabilities_invalid",
            ));
        }
        if self.provenance.iter().any(|value| value.trim().is_empty()) {
            return Err(CapabilityRankingError::new("candidate_provenance_invalid"));
        }
        if self.scope.trim().is_empty() {
            return Err(CapabilityRankingError::new("candidate_scope_invalid"));
        }
        if self.estimated_cost.is_some_and(|value| value < 0)
            || self.estimated_latency_ms.is_some_and(|value| value < 0)
        {
            return Err(CapabilityRankingError::new("candidate_cost_invalid"));
        }
        if !matches!(
            self.metric_class.as_str(),
            "unknown" | "estimated" | "measured" | "simulated"
        ) {
            return Err(CapabilityRankingError::new(
                "candidate_metric_class_invalid",
            ));
        }
        if self.freshness_seconds.is_some_and(|value| value < 0) {
            return Err(CapabilityRankingError::new("candidate_freshness_invalid"));
        }
        if !matches!(
            self.health.as_str(),
            "unknown" | "healthy" | "degraded" | "unhealthy"
        ) {
            return Err(CapabilityRankingError::new("candidate_health_invalid"));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct RankRequest {
    #[serde(default = "default_max_results")]
    pub max_results: usize,
    #[serde(default)]
    pub required_scope: Option<String>,
    #[serde(default)]
    pub required_trust: Option<String>,
    #[serde(default)]
    pub max_freshness_seconds: Option<i64>,
}

impl Default for RankRequest {
    fn default() -> Self {
        Self {
            max_results: default_max_results(),
            required_scope: None,
            required_trust: None,
            max_freshness_seconds: None,
        }
    }
}

fn trust_rank(value: &str) -> Option<i64> {
    TRUST_LEVELS
        .iter()
        .find_map(|(name, rank)| (*name == value).then_some(*rank))
}

fn policy_name(policy_eligible: Option<bool>) -> &'static str {
    match policy_eligible {
        Some(true) => "eligible",
        Some(false) => "rejected",
        None => "unknown",
    }
}

struct RankedFact {
    value: Value,
    eligible: bool,
    score: i64,
    handle: String,
    version: String,
    estimated_cost: Option<i64>,
    estimated_latency_ms: Option<i64>,
    metric_class: String,
}

pub fn rank_capabilities(
    candidates: &[CapabilityCandidate],
    required: &[String],
    request: &RankRequest,
) -> Result<Value, CapabilityRankingError> {
    let invalid_required_trust = request
        .required_trust
        .as_deref()
        .is_some_and(|value| trust_rank(value).is_none());
    let invalid_max_freshness = request.max_freshness_seconds.is_some_and(|value| value < 0);
    if required.is_empty()
        || required.iter().any(|value| value.trim().is_empty())
        || request.max_results == 0
        || request.max_results > MAX_RESULTS
        || request
            .required_scope
            .as_deref()
            .is_some_and(|value| value.trim().is_empty())
        || invalid_required_trust
        || invalid_max_freshness
    {
        return Err(CapabilityRankingError::new(if invalid_required_trust {
            "ranking_trust_invalid"
        } else if invalid_max_freshness {
            "ranking_freshness_invalid"
        } else {
            "ranking_request_invalid"
        }));
    }

    let required_set: BTreeSet<String> = required.iter().cloned().collect();
    let mut facts = Vec::with_capacity(candidates.len().min(MAX_RESULTS));
    for candidate in candidates {
        if facts.len() >= MAX_CANDIDATES {
            return Err(CapabilityRankingError::new("candidate_count_limit"));
        }
        candidate.validate()?;
        let capabilities: BTreeSet<&str> =
            candidate.capabilities.iter().map(String::as_str).collect();
        let matched: Vec<String> = required_set
            .iter()
            .filter(|value| capabilities.contains(value.as_str()))
            .cloned()
            .collect();
        let missing: Vec<String> = required_set
            .iter()
            .filter(|value| !capabilities.contains(value.as_str()))
            .cloned()
            .collect();
        let scope_match = request.required_scope.as_deref().map_or(true, |scope| {
            candidate.scope == "*" || candidate.scope == scope
        });
        let trust_match = request.required_trust.as_deref().map_or(true, |trust| {
            trust_rank(&candidate.trust).unwrap_or(-1) >= trust_rank(trust).unwrap_or(-1)
        });
        let freshness_match = request.max_freshness_seconds.map_or(true, |maximum| {
            candidate
                .freshness_seconds
                .is_some_and(|freshness| freshness <= maximum)
        });
        let policy = policy_name(candidate.policy_eligible);
        let hard_filter = json!({
            "missing_capabilities": missing.is_empty(),
            "available": candidate.available,
            "policy_eligibility": policy == "eligible",
            "scope": scope_match,
            "trust": trust_match,
            "freshness": freshness_match,
        });
        let eligible = missing.is_empty()
            && candidate.available
            && policy == "eligible"
            && scope_match
            && trust_match
            && freshness_match;
        let cost_score = candidate.estimated_cost.map(|value| -value);
        let latency_score = candidate.estimated_latency_ms.map(|value| -value);
        let availability_score = if candidate.available { 0 } else { -10_000 };
        let policy_score = match policy {
            "eligible" => 0,
            "rejected" => -10_000,
            _ => -5_000,
        };
        let scope_score = if scope_match { 0 } else { -10_000 };
        let trust_score = if trust_match { 0 } else { -10_000 };
        let freshness_score = if freshness_match { 0 } else { -10_000 };
        let score = (matched.len() as i64 * 100)
            + (missing.len() as i64 * -1000)
            + cost_score.unwrap_or(0)
            + latency_score.unwrap_or(0)
            + availability_score
            + policy_score
            + scope_score
            + trust_score
            + freshness_score;
        let reason = if !missing.is_empty() {
            "missing_required_capabilities"
        } else if !candidate.available {
            "unavailable"
        } else if policy != "eligible" {
            match policy {
                "rejected" => "policy_rejected",
                _ => "policy_unknown",
            }
        } else if !scope_match {
            "scope_mismatch"
        } else if !trust_match {
            "trust_below_floor"
        } else if !freshness_match {
            if candidate.freshness_seconds.is_none() {
                "freshness_unknown"
            } else {
                "freshness_stale"
            }
        } else {
            "eligible"
        };
        let score_components = json!({
            "matched_capabilities": matched.len() as i64 * 100,
            "missing_capabilities": missing.len() as i64 * -1000,
            "cost": cost_score,
            "latency": latency_score,
            "availability": availability_score,
            "policy": policy_score,
            "scope": scope_score,
            "trust": trust_score,
            "freshness": freshness_score,
        });
        let value = json!({
            "schema": FACT_SCHEMA,
            "handle": &candidate.handle,
            "kind": &candidate.kind,
            "version": &candidate.version,
            "matched_capabilities": matched,
            "missing_capabilities": missing,
            "trust": &candidate.trust,
            "available": candidate.available,
            "scope": &candidate.scope,
            "health": &candidate.health,
            "freshness_seconds": candidate.freshness_seconds,
            "policy_eligibility": policy,
            "eligible": eligible,
            "hard_filter": hard_filter,
            "metric_class": &candidate.metric_class,
            "estimated_cost": candidate.estimated_cost,
            "estimated_latency_ms": candidate.estimated_latency_ms,
            "score": score,
            "score_components": score_components,
            "selection_reason": reason,
            "provenance": &candidate.provenance,
        });
        facts.push(RankedFact {
            value,
            eligible,
            score,
            handle: candidate.handle.clone(),
            version: candidate.version.clone(),
            estimated_cost: candidate.estimated_cost,
            estimated_latency_ms: candidate.estimated_latency_ms,
            metric_class: candidate.metric_class.clone(),
        });
    }
    facts.sort_by(|left, right| {
        right
            .eligible
            .cmp(&left.eligible)
            .then_with(|| right.score.cmp(&left.score))
            .then_with(|| left.handle.cmp(&right.handle))
            .then_with(|| left.version.cmp(&right.version))
    });

    let measured: Vec<&RankedFact> = facts
        .iter()
        .filter(|fact| {
            fact.eligible && fact.estimated_cost.is_some() && fact.estimated_latency_ms.is_some()
        })
        .collect();
    let mut frontier = Vec::new();
    for (index, item) in measured.iter().enumerate() {
        let dominated = measured.iter().enumerate().any(|(other_index, other)| {
            if index == other_index {
                return false;
            }
            let other_cost = other.estimated_cost.expect("measured cost");
            let other_latency = other.estimated_latency_ms.expect("measured latency");
            let item_cost = item.estimated_cost.expect("item cost");
            let item_latency = item.estimated_latency_ms.expect("item latency");
            other_cost <= item_cost
                && other_latency <= item_latency
                && (other_cost < item_cost || other_latency < item_latency)
        });
        if !dominated {
            frontier.push(json!({
                "handle": &item.handle,
                "version": &item.version,
                "estimated_cost": item.estimated_cost,
                "estimated_latency_ms": item.estimated_latency_ms,
                "metric_class": &item.metric_class,
            }));
        }
    }
    frontier.sort_by(|left, right| {
        left["handle"]
            .as_str()
            .cmp(&right["handle"].as_str())
            .then_with(|| left["version"].as_str().cmp(&right["version"].as_str()))
    });

    Ok(json!({
        "schema": CATALOG_SCHEMA,
        "required_capabilities": required_set.into_iter().collect::<Vec<_>>(),
        "required_scope": &request.required_scope,
        "required_trust": &request.required_trust,
        "max_freshness_seconds": request.max_freshness_seconds,
        "candidates": facts
            .iter()
            .take(request.max_results)
            .map(|fact| fact.value.clone())
            .collect::<Vec<_>>(),
        "pareto_frontier": frontier,
        "truncated": facts.len() > request.max_results,
        "authority": "advisory_only",
        "authorization_owner": "agent-loop-runtime",
    }))
}

#[cfg(test)]
mod tests {
    use super::{rank_capabilities, CapabilityCandidate, RankRequest};
    use serde::Deserialize;
    use sha2::{Digest, Sha256};
    use std::fs;

    #[derive(Debug, Deserialize)]
    struct Fixture {
        schema: String,
        cases: Vec<FixtureCase>,
    }

    #[derive(Debug, Deserialize)]
    struct FixtureCase {
        name: String,
        required: Vec<String>,
        request: RankRequest,
        candidates: Vec<CapabilityCandidate>,
        expected_sha256: String,
    }

    fn fixture() -> Fixture {
        let path = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../fixtures/delivery/v1/issue346-capability-ranking-parity.json"
        );
        serde_json::from_slice(&fs::read(path).expect("parity fixture")).expect("valid fixture")
    }

    fn digest(value: &serde_json::Value) -> String {
        let bytes = serde_json::to_vec(value).expect("serializable ranking result");
        Sha256::digest(bytes)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect()
    }

    #[test]
    fn python_rust_filtering_and_ranking_match_golden_vectors() {
        let fixture = fixture();
        assert_eq!(
            fixture.schema,
            "simplicio.fast.capability-ranking-parity/v1"
        );
        for case in fixture.cases {
            let result = rank_capabilities(&case.candidates, &case.required, &case.request)
                .unwrap_or_else(|error| panic!("{}: {error}", case.name));
            assert_eq!(digest(&result), case.expected_sha256, "{}", case.name);
        }
    }

    #[test]
    fn invalid_requests_fail_closed_with_stable_reason_codes() {
        let candidate = CapabilityCandidate {
            handle: "candidate".to_owned(),
            kind: "worker".to_owned(),
            version: "1".to_owned(),
            capabilities: vec!["query".to_owned()],
            trust: "verified".to_owned(),
            available: true,
            estimated_cost: None,
            estimated_latency_ms: None,
            provenance: Vec::new(),
            policy_eligible: Some(true),
            scope: "*".to_owned(),
            metric_class: "unknown".to_owned(),
            freshness_seconds: None,
            health: "unknown".to_owned(),
        };
        let invalid = RankRequest {
            max_results: 0,
            ..RankRequest::default()
        };
        assert_eq!(
            rank_capabilities(&[candidate], &["query".to_owned()], &invalid)
                .expect_err("zero max_results must fail")
                .reason_code,
            "ranking_request_invalid"
        );
    }
}
