# Aicepeak product constitution

Status: Draft — requires maintainer approval.

Distilled from [AICEPEAK_NORDSTERN.md](../AICEPEAK_NORDSTERN.md) chapters 4 (principles) and 8 (domain rules) as compact review context. The north star prevails on any conflict; this file adds no scope and chooses no technology.

## Principles

1. **Company relevance before market averages.** External news changes a company figure only through a justified exposure and impact assumption.
2. **Number types stay distinct.** Actuals, budget/plan, earlier forecasts, external forecasts, qualitative statements and assumptions are never reinterpreted as each other, in inputs or outputs.
3. **Audit trail, not black box.** Sources, data, assumptions, calculations and results form an accessible trail. Hidden model reasoning is not part of it.
4. **Human control takes effect.** Corrections and confirmed assumptions change the basis actually used; new AI suggestions never silently replace confirmations.
5. **Quantification needs a basis.** A plausible explanation or relevance score alone never justifies an exact amount or percentage.
6. **Consistency over false precision.** Periods, units, signs and totals fit together; uncertainty, gaps and limits are shown actively.
7. **New information changes expectations deliberately.** An influence already included never counts again through another report.
8. **Reproducible despite uncertainty.** A saved calculation state stays verifiable, even for uncertain or probabilistic forecasts.
9. **No arbitrary defaults.** Time grids, size limits, budgets and quality thresholds are not copied from earlier implementations.
10. **Regular use must be practical.** Quality and effort are judged together; no model or vendor is mandated or excluded.
11. **Dialogue is bound to context.** Questions, user statements and accepted changes stay distinguishable; a prompt never replaces a calculation basis.

## Domain rules

- Evidence is typed: observed figure, external forecast, company statement, hypothesis and confirmed assumption differ. Confirmation means deliberate use, not proven truth.
- Numbers keep their context: period, value type, currency, unit, sign, scope and source. Missing is not zero.
- Every additional effect is judged against a named baseline that may already contain the development.
- Correlation or plausibility is not causation; impact and strength need their own basis or an explicit assumption.
- One event may affect several positions, but the same economic effect is never counted twice.
- Quantities, prices and time fit: price × matching quantity; price changes need a reference base; percent ≠ percentage points; contract shares, units and periods agree.
- Aggregation respects the value type: flows sum over periods, balances do not; no double-counted subtotals; margins are not averaged without their base.
- Uncertainty stays consistent in totals: a sum of medians or band limits is not the median or band of the total.
- Calculation state and knowledge state stay separate: later knowledge may re-evaluate an old forecast, never claim it was used then.
- Corrections are effective and traceable: old results, pending recalculation and new results are distinguishable.
- Result and explanation match: a cited driver actually belongs to the selected result.
- Dialogue inputs keep their status: questions, hypotheticals, targets and effective change requests stay distinct; no invented facts or pretended recalculation.
- Methods, models or many sources never hide missing company data.

## Transparency test

For any selected position and period a controller can see: the value, unit and meaning; the data and forecast version and what is actual, plan or assumption; the sources and original passages, and what was excluded or not quantified; the exposure and impact assumption linking driver to position; the calculation and how it enters totals; the decisive uncertainties and gaps; and which changes require a recalculation. A bare source list or a generic AI explanation does not pass.
