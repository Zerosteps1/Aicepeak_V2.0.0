# Validation of the specification sheet and target architecture by GPT-6 Astra (reasoning effort `max`)

| Field | Value |
|---|---|
| Date | 2026-10-28 |
| Document under review | `docs/architecture/AICEPEAK_SPEC_AND_ARCHITECTURE.md`, version 0.1 draft (the pre-validation state; the resolutions below were applied afterwards and produced version 0.2, which is the version in this PR and has not been re-validated) |
| Run | Started 2026-10-28 16:49 CET, finished 18:21 CET (about 92 minutes); the result conforms to the output schema |
| Reviewer | `gpt-6-astra`, reasoning effort `max`, via OpenAI Codex CLI 0.164.0 (`codex exec`), ChatGPT Business login, live web search enabled, user configuration ignored |
| Isolation | Linux container (`node:22-bookworm-slim`, Docker 29) with the validation folder mounted read-only as the working directory, a fresh `CODEX_HOME` holding only a copy of the login file, no other host paths mounted; Codex's own sandbox disabled inside the container (the container is the sandbox), as the repository's factory does for its workers |
| Inputs in the working directory | the document under review; `AICEPEAK_NORDSTERN.md` (north star, `main`); the draft chapter 12 of the north star and the draft product constitution from PR #4; the prompt and the output schema below |
| Independence | Fresh context without the author's conversation; the reviewer saw only the files listed above and the public web |
| Cost | ChatGPT Business subscription allowance; no API billing |

## Prompt

```text
You are an independent validation panel reviewing a draft architecture document before it goes to the maintainers of a software product. Act in three roles at once and keep all three perspectives in your findings:

1. Principal enterprise architect with experience in SaaS financial software that is also deployed into customers' own cloud accounts.
2. EU data-protection and AI-regulation counsel (GDPR, EU AI Act, EU Data Act, NIS2, DORA, Cyber Resilience Act).
3. CISO and procurement lead of a large European industrial group evaluating whether this vendor could be approved.

Working directory contents (read all of them fully before judging):

- `AICEPEAK_SPEC_AND_ARCHITECTURE.md`: the document under review (English).
- `AICEPEAK_NORDSTERN.md`: the product north star (German). It is the authoritative product scope. Its chapter 1.1 defines the status labels G (set), P (precision pending approval), Q (source proposal) and O (optional extension) and the decision points D-xx. Its chapter 11.2 lists what is explicitly undecided. Principle 9 and section 9.1 forbid invented numeric defaults and promises.
- `NORDSTERN-chapter12-draft-pr4.md`: draft skeleton of the north star's chapter 12 (decision points D-01..D-11), not yet merged.
- `CONSTITUTION-draft-pr4.md`: draft product constitution distilled from the north star, not yet merged.

Your task: validate the document under review and report per the output schema that was given to you. Review dimensions, in this priority:

A. North-star conformity. Every requirement with status G or P (AIC-001 to AIC-048, AIC-050, and AIC-044 to AIC-046) must be covered by concrete architecture elements, not by restating the requirement. Optional items (AIC-049, AIC-051 to AIC-055) and the decision points D-01..D-11 must not be presented as decided or committed. Check that the document does not reinterpret the north star's domain rules (chapter 8) and that it keeps the distinctions the north star insists on (value types, evidence types, baseline, confirmations, draft vs current, question vs change order).
B. Regulatory accuracy. Verify every statement about GDPR, the EU AI Act (including applicability dates and the high-risk classification argument), the EU Data Act, NIS2, DORA, the Cyber Resilience Act, and standards (ISO/IEC 27001, 42001, SOC 2, C5, TISAX). Use live web search to check dates, article numbers and current legislative status (for example the "Digital Omnibus" proposals of November 2025) and cite the URLs you used in the evidence field. Flag any claim that is wrong, outdated or stated more confidently than the sources allow.
C. Security and privacy architecture. Look for gaps a corporate security review would find: tenant isolation, key management, egress control, prompt-injection and document-parsing risks, secrets, supply chain, logging of personal data, retention and deletion, backup handling of deleted data, admin access, BYOC operating model, LLM provider data handling. Verify vendor claims (AWS, Azure, Bedrock, Azure OpenAI, OpenAI, Anthropic, Mistral) with web search where the document makes a specific claim.
D. Architecture quality and feasibility. The team is two people plus AI coding agents. Judge whether the design is operable at that size, whether it is over- or under-engineered for the stated editions, whether the deterministic engine and reproducibility story is sound, and whether the AI layer design actually enforces "AI proposes, humans confirm, numbers come only from calculations".
E. Consistency and clarity. Contradictions between Part A (specification sheet) and Part B (architecture), between text and diagrams, undefined terms, and places where a reader could mistake a proposal for a decision.

Rules for findings:

- Severity: P0 = would make a corporate security or legal review fail, or contradicts a set (G) north-star requirement; P1 = material gap or error that must be fixed before maintainers rely on the document; P2 = improvement.
- Each finding must point to a section of the document under review and quote or paraphrase the passage. Do not report the same issue twice. Prefer fewer, well-evidenced findings over long lists; stop at 40 findings.
- Do not propose new product scope beyond the north star. Do not rewrite the document; recommend concrete changes.
- Where you are unsure, say so in the confidence field rather than omitting the finding.
- Use web search for facts, not for opinions. Cite the URL in the evidence field for every regulatory or vendor fact you verified.

Produce only the JSON object required by the output schema as your final answer.

Isolation rules: read only the files in the working directory and nothing else on this machine; do not delegate work to sub-agents; use web search only to verify regulatory and vendor facts.
```

## Run notes

- A first attempt ran Codex directly on the maintainer's machine with `--sandbox read-only`. That sandbox prevents writes but allows reading the whole disk, and the reviewer started listing files outside the working directory (notes in the maintainer's personal knowledge base) before the run was stopped after a few minutes. The run was aborted, its output discarded, and the log deleted; the content read in that window went to the ChatGPT Business workspace of the maintainer, which is covered by its no-training terms. The lesson is recorded here because it is exactly the failure the repository's factory isolates against: a read-only sandbox is not a confinement.
- The second attempt, whose results are reported below, ran inside a container with only the validation folder mounted. Two environment details were needed: the container image lacks system CA certificates (Codex's HTTP client then fails with "workspace routing discovery failed"), and the container's IPv6 route was disabled. The isolation rule sentence was appended to the prompt for this run. The run log shows reads of the seven mounted files and web searches only; no other path existed in the container.
- The maintainers' side of this report (the resolutions) was written by the author of the document with Claude Fable 5.1, not by the reviewer. Regulatory and vendor facts the reviewer cited were accepted where they could be checked against the document, the official texts named in the document's Appendix B and the author's own research notes; three items could not be independently re-verified and are marked "to confirm" in the resolutions (the C5:2026 transition rule in its section 3.5, the exact contractual geography of OpenAI's EU residency endpoint, and the final status of the Code of Practice on AI-generated content).

## Output schema

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["overall_verdict", "summary", "nordstern_coverage", "findings", "questions_for_maintainers"],
  "properties": {
    "overall_verdict": { "type": "string", "enum": ["ready_for_maintainer_review", "needs_revision", "not_acceptable"] },
    "summary": { "type": "string" },
    "nordstern_coverage": {
      "type": "object",
      "additionalProperties": false,
      "required": ["missing_requirements", "promoted_optional_items", "invented_commitments"],
      "properties": {
        "missing_requirements": { "type": "array", "items": { "type": "string" } },
        "promoted_optional_items": { "type": "array", "items": { "type": "string" } },
        "invented_commitments": { "type": "array", "items": { "type": "string" } }
      }
    },
    "findings": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["id", "severity", "category", "section", "claim", "evidence", "recommendation", "confidence"],
        "properties": {
          "id": { "type": "string" },
          "severity": { "type": "string", "enum": ["P0", "P1", "P2"] },
          "category": { "type": "string", "enum": ["nordstern_conflict", "regulation", "security", "architecture", "feasibility", "consistency", "clarity"] },
          "section": { "type": "string" },
          "claim": { "type": "string" },
          "evidence": { "type": "string" },
          "recommendation": { "type": "string" },
          "confidence": { "type": "string", "enum": ["high", "medium", "low"] }
        }
      }
    },
    "questions_for_maintainers": { "type": "array", "items": { "type": "string" } }
  }
}
```

## Result

**Verdict: `needs_revision`.** The reviewer found the structure sound (shared SaaS and BYOC components, isolated engine, explicit evidence and value types, proposal states, complete traceability), confirmed that no optional north-star item was promoted and no commitment was invented, and listed 35 findings, of which the ten P0 findings fall into two groups: three conflicts with set north-star requirements (the temporal model could not hold revisions of the same period, the state model excluded adopted corrections from the engine, dialogue presupposed a forecast) and seven security or legal gaps a corporate review would fail (tenant isolation mechanism, administrator export bypass, key coverage, deletion end to end, incompatible residency promises, overstated BYOC claims, audit rights restricted to one edition). The reviewer's own summary ends: "These are fixable within the north star, but maintainers should not rely on the document as an implementation or procurement baseline until the findings are resolved."

| Measure | Value |
|---|---|
| Findings | 35 (P0: 10, P1: 21, P2: 4) |
| By category | security 12, regulation 9, architecture 8, north-star conflict 4, feasibility 1, consistency 1 |
| North-star requirements judged only partially or nominally covered | 20 (listed below with their resolution) |
| Optional items presented as decided | 0 |
| Invented commitments | 0 |
| Questions for the maintainers | 9 |
| Resolution in version 0.2 | 35 fixed in the document (3 of them also need a maintainer decision and are listed in Appendix D of the document); 0 disputed |

**North-star coverage.** The reviewer listed 20 requirements as partially or nominally covered. Every one of them is addressed by a finding's fix in version 0.2:

| Requirement | Reviewer's gap | Resolved by |
|---|---|---|
| AIC-003 | Successive knowledge revisions for overlapping periods could not be retained or queried by knowledge time | F-01 |
| AIC-006 | No enforceable arithmetic rules for units, cumulative values, percentage points | F-06 |
| AIC-007 | Corrected values entered a state the engine did not read | F-02 |
| AIC-019 | Effects already contained in the baseline were not represented | F-05 |
| AIC-020 | Numbers in explanations were not bound to calculation results | F-04 |
| AIC-021 | Aggregation rules without a typed calculation contract | F-06 |
| AIC-022 | Snapshot identity confused with execution identity; no replay-environment retention | F-10 |
| AIC-023 | No joint-uncertainty representation; scenario spreads not separated from probabilistic measures | F-06 |
| AIC-027 | Comparisons without alignment mechanisms | F-08 |
| AIC-028 | ConflictFlagged conflicted with "only Confirmed is effective" | F-02 |
| AIC-030 | Adopted corrections not consistently usable | F-02, F-11 |
| AIC-032 | Export verified only in its original state | F-09 |
| AIC-033 | No edited-state indicator, no stale markings | F-09 |
| AIC-034 | Dialogue required a version and a run | F-03 |
| AIC-035 | Numeric and causal claims not verified against the run | F-04 |
| AIC-042 | Reconciliation stated without movement schedules | F-07 |
| AIC-043 | Payment timing and working capital not represented | F-07 |
| AIC-044 | Isolation, key coverage, disclosure and deletion assurances without complete mechanisms | F-23, F-25, F-26, F-27, F-28, F-30 |
| AIC-046 | Changeable labels inside immutable records without an event model | F-11 |
| AIC-048 | Incorrect cut-off query; comparisons without alignment and revision selection | F-01, F-08 |

## Findings and resolutions

Each finding is listed with the reviewer's severity and the maintainers' resolution: **fixed** (the document was changed; the change is named), **disputed** (not changed, with the reason), or **decision needed** (a maintainer decision is required; listed in Appendix D of the document). The reviewer's full claim, evidence (with the URLs it cited) and recommendation for each finding are in the raw result file next to this report.

| ID | Sev. | Category | Section (v0.1) | Finding in one sentence | Resolution in v0.2 |
|---|---|---|---|---|---|
| F-01 | P0 | north-star conflict | B11 bitemporal model | An exclusion constraint on (key, valid period) could not hold revisions of the same period, and "latest row recorded before the cut-off" used write time instead of knowledge time (AIC-003, 022, 048). | **Fixed.** B11 now defines revision tables with `knowledge_time`, `revision_id`, supersession and a partial unique index over effective rows only; two queries (effective, as-known-at in two modes) that never use `recorded_at`; tests for late ingestion, revised actuals and supersession. B4 and B6 reference the model. |
| F-02 | P0 | north-star conflict | B5 state model | "Only Confirmed is read by the engine" excluded Corrected and ConflictFlagged values, contradicting effective corrections and protected confirmations (AIC-007, 028, 030, S-02, S-12). | **Fixed.** B5 has a two-dimensional state model: adoption status (Proposed, Adopted, Rejected, Superseded; a correction is an adopted revision) and review flags (ConflictFlagged, RecheckRequired) that never change what is effective; an explicit engine-eligibility rule; S-02 and S-12 named as regression tests. |
| F-03 | P0 | north-star conflict | B4, B7 | Dialogue was bound to a version and received only "the selected version", excluding the pre-forecast dialogue AIC-034 requires; "only the confirmed basis" contradicted T1, T2 and T4. | **Fixed.** B7 defines five dialogue context types (onboarding, source review, working basis, imported-forecast review, saved-run explanation); a version is referenced only in the last; context minimisation is specified per task class with every item labelled by status; B4 DialogueThread updated. |
| F-04 | P1 | architecture | B7 T6, structured output | Schema validation and allowed citations did not stop a model from emitting an invented amount or an unsupported causal claim. | **Fixed.** B6 and B7: T6 and T7 outputs are typed assertions; numbers are references rendered from the store, causal statements are references to exposure and impact links validated against the selected run; free-text numbers are rejected. |
| F-05 | P1 | architecture | B4 Baseline, EventCluster; B6 | Duplicate-news detection existed, but not the representation of an effect already contained in the baseline (AIC-019). | **Fixed.** B4 adds the Effect entity with the baseline revision it was judged against and an inclusion decision (additive, contained, partially contained, undecided); undecided effects stay out of the calculation and visible; the once-only invariant is in B6; B5 step 7 updated. |
| F-06 | P1 | architecture | B6 kernel, uncertainty, verification | The plug-in interface was too abstract to enforce chapter 8; rerunning the same engine verified repeatability, not correctness. | **Fixed.** B6 defines Quantity, Expression, Aggregation and Uncertainty contracts with checked arithmetic and conversions, two uncertainty types that are never mixed, kernel invariants as run-time assertions, and an engine-independent expected-result suite from the north-star scenarios; tolerances and thresholds stay D-10. |
| F-07 | P1 | architecture | B6 kernel; D-02 | Balance sheet and liquidity support was one sentence; no movement or payment-timing structures (AIC-042, 043, S-16). | **Fixed.** B6 introduces movement schedules and payment-timing assumptions as generic objects, the reconciliation invariants, the S-16 walk-through and the `not modelled` behaviour; D-02/D-07 remain open and the proposal row was updated. |
| F-08 | P1 | architecture | B4 ForecastVersion; B6 | Comparison records had no attributes for alignment, currency, scope or actual-revision selection (AIC-027, 048). | **Fixed.** B4 defines the Comparison contract (sides with revision selection by knowledge time, period alignment, unit and currency treatment, line-item mapping, scope bridge, sign convention, metric ids, non-comparability reasons); B6 "Backtests and comparisons" uses it; thresholds remain D-10. |
| F-09 | P1 | north-star conflict | B14 export; AS-6 | Parity was checked only for the original workbook; no edited-state designation; the D-01 fallback lacked the north star's lower bound (AIC-032, 033). | **Fixed.** B14 adds input-mutation parity, an edited-state indicator and stale markings for frozen outputs, and a floor for D-01 (mandatory controller edits always live); AS-6 and the D-01 proposal row say the same. |
| F-10 | P1 | architecture | B4 InputSnapshot, B6 manifest | The snapshot hash was called the run's identity; no retention of executable environments; a seed alone does not fix a NumPy stream. | **Fixed.** B6 "Three identities" (snapshot hash, calculation-specification hash, execution id), replay-artefact retention for the forecast retention period, contained replay of vulnerable images, and the NumPy compatibility statement in the numerics row; B4 rows updated. |
| F-11 | P1 | architecture | B5, B11, B14 | Append-only tables had no event semantics for labels, adoptions and later attestations; concurrent edits and retries could leave ambiguous states. | **Fixed.** B5 "Adoption, labels and attestations as append-only events": three event streams with read projections, expected-previous concurrency checks, transactional snapshot sealing, idempotent result publication and job re-run as the only recovery; B4 ForecastVersion describes label events. |
| F-12 | P0 | regulation | A8, B15.2, B15.6 | Audit and inspection rights were reserved for the Dedicated edition, contrary to GDPR Art. 28(3)(h) and DORA Art. 30(3)(d)/(e), which follow the function, not the hosting. | **Fixed.** B15.2 grants audits including inspections in both editions with a proportionate procedure (evidence package, remote or on-site inspection, pooled audits, tenant-scoped); B15.6 grants Art. 30(3) access, inspection, audit and threat-led testing per function in both editions and declines a use it cannot support; A4, A8, B15.1 updated. |
| F-13 | P1 | regulation | A8, B15.5 | The NIS2 scope test treated size as an absolute exemption, called large cloud providers "important" and put managed service providers in Annex II. | **Fixed.** B15.5 is now a five-element assessment (services in Annex I sectors 8 and 9, size under Recommendation 2003/361/EC, size-independent routes of Art. 2(2)–(4), essential versus important under Art. 3, establishment under Art. 26) with the direct obligations that would activate; A8, B15.1 and Appendix B corrected. |
| F-14 | P1 | regulation | Executive summary, B15.3 | "AI-free core" and "a reclassification would be a documentation exercise" went beyond the evidence; determinism does not exclude AI; Art. 25(1)(c), 17, 9 and 43 were not reflected. | **Fixed.** B15.3 assesses the engine method by method, cites Art. 25(1)(c) for a changed intended purpose, treats Art. 6(3) as a fact-specific assessment not relied on, and replaces the readiness claim with a maintained gap assessment; the executive summary and A8 are reworded. |
| F-15 | P1 | regulation | B15.3 Art. 50(2) | A metadata field and an export column did not substantiate "follows the Code of Practice". | **Fixed, labelled as a proposed implementation.** B15.3 assesses per output type, specifies the provenance record, API field, UI label, export columns and cell metadata, pass-through of provider provenance, the detection path and a transformation test suite; adequacy against the final Code of Practice is to confirm (Appendix D item 6). |
| F-16 | P1 | regulation | A4, A7, B15.2, B15.7 | Clocks ran from "confirmation" instead of awareness; CRA final-report periods were given without their different starting events. | **Fixed.** B13 contains an incident matrix (GDPR processor and controller, NIS2 customers and own scope, CRA Art. 14 with both final-report triggers, DORA Art. 19, contractual) with a definition of awareness; A4, A7, B15.2 and B15.7 use it. |
| F-17 | P1 | regulation | A7, B15.7 | A 12-month LTS line was not reconciled with the five-year CRA support period or the ten-year availability of issued updates. | **Fixed.** A7 separates release-line maintenance (12 months, proposed), the support period (Art. 13(8), at least five years), update availability (Art. 13(9), ten years) and the Art. 13(10) free migration path; B15.7, A8 and Appendix B state the same. |
| F-18 | P1 | architecture | B11, B14, B15.4 | Unconditional full-export promises were not reconciled with licensed and paywalled third-party content; Data Act Art. 2(38) excludes protected assets. | **Fixed.** B14 records licence permissions per use; B11's export manifest distinguishes customer data, licensed evidence (full or reference-only) and Aicepeak assets; B15.4 states the contractual specification and exclusions; a risk row was added. |
| F-19 | P2 | regulation | B15.8, Appendix B | The C5:2026 transition was misstated, the TISAX ISA2027 transition omitted, and "mappings, not redesigns" unsupported. | **Fixed, to confirm.** B15.8 states the section 3.5 rule (Type 1 by assessment date, Type 2 by examination period start, on or after 1 June 2027) as cited by the reviewer, names ISA2027, requires a gap assessment per scheme and distinguishes planned from obtained assurance. The section 3.5 wording was not re-verified against the BSI text by the author. |
| F-20 | P2 | regulation | Appendix B, B15.2 | The GDPR reform was labelled COM(2025) 836 (that is the AI Omnibus); the direction of the final text was stated too confidently. | **Fixed.** COM(2025) 837 with procedure 2025/0360(COD) and the Parliament document link; the "would relax, not tighten" sentence replaced by a change-assessment duty in the compliance register. |
| F-21 | P2 | security | A4 | The comparison with CISA BOD 19-02 was wrong (high is equal, not stricter), the "only benchmark" claim unsupported, and a clock from confirmation can be slower than one from detection. | **Fixed.** A4 defines detection, triage and remediation clocks, measures targets from detection, prioritises exploited vulnerabilities, and states the BOD 19-02 comparison correctly; Appendix B has the reference. |
| F-22 | P1 | regulation | B11, B15.2, B15.9, AS-8 | Originals with person-level rows were retained while "not stored by default" was claimed; the DPIA expectation and the BDSG § 38 trigger were too narrow. | **Fixed.** B11 defines the restricted-source policy (retain restricted, redact, or reject); B15.2 screens the DPIA on the tenant's actual categories with the applicable WP248 criteria; B15.9 adds the headcount-independent § 38(1) triggers; AS-8 corrected. |
| F-23 | P0 | security | B1, B9 | Per-tenant databases and signed tokens did not say how a shared worker is bound to one tenant's credentials; the nightly `row_security = off` proof was technically wrong. | **Fixed.** B9 specifies per-tenant database roles obtained through the in-API credential broker from the authenticated token or signed job record, STS session policies and delegation SAS for storage, KMS grants per tenant, sandbox and engine pods without credentials; the RLS count is replaced by adversarial isolation tests on every release; a pooled-table migration is a new security decision; B1, A4 and AD-05 updated. |
| F-24 | P0 | security | B8 roles | The tenant administrator could obtain all content through export despite being denied content reads. | **Fixed; decision needed (D-06).** B8 makes the administrator configuration-only with a two-person rule for exports and deletions, offers an optional content-privileged tenant owner, and states that export paths enforce read permissions; Appendix D item 11 asks which model tenants get. |
| F-25 | P0 | security | A4, B9, B11 | Revocation of the customer key did not render all data unreadable; no project-key hierarchy; indexes and metadata unaccounted for. | **Fixed.** B9 defines the three-level key hierarchy with project keys and a key-coverage matrix per data class (what revocation covers, what the ledger removes); A4 and B11 narrow the erasure claim accordingly. |
| F-26 | P0 | security | A7, B11, B15.2 | Deletion was not designed across originals, derivatives, indexes, backups and restores; the offboarding clock contradicted the backup window; certificates would overstate completion. | **Fixed.** B11 introduces the deletion ledger outside the backups it governs, ledger replay on every restore, a deletion-by-class table, reconciled clocks and a certificate that lists exclusions and pending expiry; A4 and A7 match. |
| F-27 | P0 | security | A3, A8, B7, B11 | Single-region storage promises, cross-region inference profiles and second-region backups were incompatible; the OpenAI fallback did not establish strict EU-only processing. | **Fixed; decision needed.** B11 defines two residency profiles with five separately declared boundaries; B7 registers every endpoint with verified geography and retention and enables fallbacks fail closed; OpenAI's EU endpoint is admitted only to the multi-region profile after contractual confirmation (to confirm); A3 updated; Appendix D item 14 asks which commitment is sold. |
| F-28 | P0 | security | B12, B15.2, B15.10 | "Customer data never leaves the account" ignored external inference, and BYOC was presented as avoiding foreign lawful-access exposure. | **Fixed.** B12 limits the no-content statement to the release and heartbeat channel and adds the outbound-flow table (the Dedicated edition's processor list); B12, B15.2 and B15.10 describe BYOC as an operating-control measure and assess residual exposure per provider and plaintext path. |
| F-29 | P1 | security | B3, B12, B14 | Application-layer controls were assigned to a CONNECT tunnel that cannot inspect them; private model endpoints were not restricted. | **Fixed.** B3 and B14 split destination control (proxy, with client authentication) from application-layer checks (fetch service), with end-to-end TLS; A6 and B12 restrict the Bedrock VPC endpoint and the Azure private endpoint to the gateway identity. |
| F-30 | P1 | security | B5, B7, B10 | Host allow-lists did not prevent disclosure of confidential figures through permitted search queries. | **Fixed; decision needed (D-06).** B7 adds the research disclosure policy proposal with query validation in the fetch service and injection evaluations; B10 and B14 reference it; Appendix D item 13 asks whether confidential figures may ever appear in queries. |
| F-31 | P1 | security | B10, B14 | The export did not distinguish trusted formulas from untrusted text that openpyxl would interpret as a formula. | **Fixed.** B14 requires explicit text cell types for all document, user and model text, formulas only from the kernel compiler, and workbook validation before release; B10 has a threat row for it; Appendix B cites the openpyxl behaviour. |
| F-32 | P1 | security | B8 | Deprovisioning was promised "at the next token check" although IdPs provision in cycles; MFA assurance was unspecified without a claim. | **Fixed.** B8 defines server-side account and grant checks, immediate session revocation on SCIM deactivation, token-lifetime bounds (proposed 15 minutes), the resulting revocation bound, provisioning-failure alerts, and per-profile MFA assurance mapping or documented IdP policy with fail-closed handling. |
| F-33 | P1 | security | B10, B11, B13 | Governance-mode Object Lock can be bypassed by privileged principals; the anchor cadence differed (daily versus hourly); no privileged-attacker boundary. | **Fixed.** B11 places anchors in a separate account with the bypass permission denied by organisation policy, a KMS signing key no platform role can change alone, optional customer-held checkpoints and a versioned verification tool; B10 states the attacker boundary; the cadence is hourly in B3, B10, B11 and B13. |
| F-34 | P1 | feasibility | A7, B12, B13, B17 | Two-person operability was asserted without a support matrix, capacity evidence or coverage plan; backup-test terminology was inconsistent. | **Fixed as far as a document can; decision needed.** B12 adds the phased qualification plan, B13 states human coverage and makes service levels conditional on qualification reports and a fleet-cost model, A7 adds the operating-responsibilities row and consistent backup-test terms (also B11), the risk table and AS-2 are updated; capacity evidence itself will exist only after the first qualification report; Appendix D item 15 asks about the order and coverage. |
| F-35 | P2 | consistency | B2 | "No inbound integration" contradicted the REST API and SCIM. | **Fixed.** B2's diagram and text show three inbound authenticated paths (users, API clients, IdP) and one outbound chokepoint. |

Severity and category are the reviewer's. No finding was disputed; where the fix depends on a maintainer decision, the finding says so and the decision is listed in Appendix D of the document (items 11 to 18).

## Questions the reviewer raised for the maintainers

The reviewer asked nine questions. Each is recorded in Appendix D of the document (item numbers in brackets) so that the maintainers answer them where the other open decisions live.

1. D-01: which results remain editable and recalculable per method, and which may stay frozen, while preserving the mandatory quantity, price, growth, cost and payment-assumption edits (item 17; the floor is now stated in B14).
2. D-02/D-07: which accounting detail and cash-flow presentation (direct, indirect, both) and which movement and payment assumptions per scope (item 18; B6 derives both presentations from the same schedules).
3. D-06: content-privileged or configuration-only tenant administrators, with separately granted export, support-access and self-grant capabilities (item 11; configuration-only with a two-person rule is the proposed default).
4. D-06: retention and erasure policy for originals, historical calculation evidence, dialogue and legal holds, and the delimitation of simultaneously current versions by period and scenario (item 12).
5. D-06: whether research queries may contain confidential figures and plans or need a separate tenant policy (item 13; the proposed default is no).
6. Residency: strictly EU member states, a broader EEA/Switzerland geography, or a selectable policy with separately declared inference, backup, support and metadata locations (item 14; two profiles are proposed in B11).
7. BYOC default operating model and ownership of emergency patching, incident reporting, restore execution and unavailable-key recovery (item 5, extended).
8. Which cloud and provider profiles are qualified first, and whether broader simultaneous support is backed by additional operating coverage or deferred (item 15; a proposed order is in B12).
9. D-09/D-10: which representative workloads, independent expected-result cases and runtime environments approve cost, availability, reproducibility and forecast-quality targets (item 16).

## How to reproduce

```sh
# on the host: a folder with the inputs (read-only) and a fresh CODEX_HOME holding only auth.json
docker run --rm --sysctl net.ipv6.conf.all.disable_ipv6=1 \
  -v "$INPUTS:/work:ro" -v "$FRESH_HOME:/codex-home" -e CODEX_HOME=/codex-home -w /work \
  node:22-bookworm-slim sh -c '
    apt-get update -qq && apt-get install -y -qq ca-certificates >/dev/null 2>&1
    npm i -g @openai/codex@0.164.0 >/dev/null 2>&1
    codex --search exec --skip-git-repo-check --ignore-user-config \
      --sandbox danger-full-access -c approval_policy="never" -C /work \
      -m gpt-6-astra -c model_reasoning_effort="max" \
      --output-schema /work/schema.json -o /codex-home/result.json "$(cat /work/prompt.md)"'
```

The raw `result.json` is stored next to this report as `2026-10-28-gpt-6-astra-max.result.json`, unchanged; the run log contains no customer data and is not committed. A second run on version 0.2 would use the same inputs with the revised document and is the recommended next step before the maintainers rely on the document.
