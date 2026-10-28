# ARCH-001 – Specification sheet and target architecture for the enterprise editions

Status: ordered by Gabriel on 2026-10-28 (chat session, decisions recorded in the document itself). This task authorizes work only once a human-reviewed PR has merged it to protected `main`; the implementing PR is reviewed against this task on that base.

```factory-task
{"status":"approved","kind":"factory","allowed_paths":["docs/architecture/","docs/work/ARCH-001.md"]}
```

requirements: []

`kind` is `factory` only because the engine knows no documentation kind and `product` stays blocked while `northstar_approved` is `false`. The task changes neither product scope nor the north star; it adds documentation under `docs/architecture/`.

## Goal

Maintainers and prospective enterprise customers can read one English document that (a) states what Aicepeak offers in which edition (specification sheet) and (b) defines the target architecture that lets corporations use the product under GDPR, the EU AI Act and related regimes, with every north-star requirement traced to an architecture element and every open product decision marked as a proposal.

## Non-goals

- No product code, no stack scaffolding, no infrastructure, no CI changes.
- No change to `AICEPEAK_NORDSTERN.md`, `docs/CONSTITUTION.md` or `docs/decisions/`; decision points D-01..D-11 stay open and are only given proposals.
- No vendor contracts, certifications or legal opinions; the document names what must be obtained and verified.
- No commitments to numeric targets (availability, run times, limits, prices): numbers appear only as proposals pending D-09/D-10.

## Context and constraints

- North star: `AICEPEAK_NORDSTERN.md` (chapters 1–11; chapter 12 skeleton in draft PR #4). It explicitly leaves architecture, data model, cloud, providers and calculation methods open (§1, §11.2) and forbids invented defaults (principle 9, §9.1).
- Decisions taken by Gabriel on 2026-10-28: editions = multi-tenant SaaS (EU) and dedicated instances in the customer's cloud account (AWS or Azure); SaaS LLM access through an Aicepeak-operated gateway with zero-retention terms, customer-chosen endpoints for dedicated instances; first customers EU industrial/retail/services groups, financial-sector customers later; AWS EU as reference host, Azure as second target, Entra ID federation.
- Language: English (ADR-0004, draft PR #4).
- Validation: an independent GPT-6 Astra review at reasoning effort `max` is recorded under `docs/architecture/validation/` with every finding and its resolution.

## Acceptance criteria

1. AC-1: The document `docs/architecture/AICEPEAK_SPEC_AND_ARCHITECTURE.md` shall contain a specification sheet (Part A) and a target architecture (Part B) in English.
2. AC-2: For every requirement AIC-001 to AIC-055 of the north star, the traceability section shall name at least one architecture element or state "optional, not in scope" for O-items.
3. AC-3: If the document states a numeric target (availability, RPO/RTO, limits, run times, retention periods), then it shall label the number as a proposal pending D-09 or D-10 and shall not present it as a commitment.
4. AC-4: Where the document touches a north-star decision point D-01..D-11, it shall mark its content as a proposal and shall not record a decision.
5. AC-5: The compliance section shall map GDPR, EU AI Act, EU Data Act, NIS2, DORA and the Cyber Resilience Act to concrete architecture controls and evidence artefacts, with primary-source references and dates.
6. AC-6: The validation report `docs/architecture/validation/2026-10-28-gpt-6-astra-max.md` shall list the prompt, the output schema, every finding with severity, and for each finding one of: fixed, disputed with reason, or decision needed.
7. AC-7: If the document links to another repository file, then the link shall resolve on protected `main` at the time of merge (`verify.py --structure-only` passes).

## Verification

```sh
python3 tools/factory/verify.py --root . --structure-only
for id in $(grep -o 'AIC-0[0-5][0-9]' AICEPEAK_NORDSTERN.md | sort -u); do grep -q "$id" docs/architecture/AICEPEAK_SPEC_AND_ARCHITECTURE.md || echo "missing $id"; done
```

Expected output:

- `verify.py` prints its `PASS:` line for structure and exits with code 0;
- the loop prints nothing (every AIC id appears in the architecture document).

## Handoff

The PR that implements this task contains exactly one handoff block:

```factory-handoff
{"runner":"claude","task":"docs/work/ARCH-001.md","owner":"Zerosteps1"}
```

## Open questions

- Which of the architecture decisions AD-01..AD-12 in the document become ADR-0006 ff. after draft PR #4 (ADR-0001..0005) is merged: Gabriel and Felix.
- Timing of the north-star approval (`northstar_approved`) and of decision points D-01..D-11, which several proposals in the document depend on: Gabriel.
