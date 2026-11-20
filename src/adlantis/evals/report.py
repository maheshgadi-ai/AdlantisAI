"""Writes the evaluation report. It states the results whichever way they come out."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean

from adlantis.evals.harness import EvalResults
from adlantis.evals.metrics import RunMetrics
from adlantis.evals.pairwise import PairResult

_MODES = (("team", "Agent team"), ("baseline", "Single-prompt baseline"))


def _average(runs: list[RunMetrics], value) -> float:
    return mean(value(run) for run in runs) if runs else 0.0


def _summary(results: EvalResults) -> list[str]:
    lines = [
        "| Profile | System | Runs | Scored | Fabricated or regulated claims "
        "| Paraphrased approved facts | Uncited but true | Calls to action (not claims) "
        "| Forbidden phrases | Rule errors | Caught in review | Citation coverage "
        "| Hard-limit compliance | Cost per run | Seconds per run |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- "
        "| --- |",
    ]
    for profile in sorted({run.profile for run in results.runs}):
        for mode, label in _MODES:
            runs = [r for r in results.runs if r.profile == profile and r.mode == mode]
            done = [r for r in runs if r.status == "ok"]
            lines.append(
                f"| {profile} | {label} | {len(runs)} | {len(done)} "
                f"| {sum(r.fabricated_or_regulated for r in done)} "
                f"| {sum(r.paraphrased_facts for r in done)} "
                f"| {sum(r.uncited_true for r in done)} "
                f"| {sum(r.calls_to_action for r in done)} "
                f"| {sum(len(r.forbidden_hits) for r in done)} "
                f"| {sum(r.rule_errors for r in done)} "
                f"| {sum(r.caught_in_review for r in done)} "
                f"| {_average(done, lambda r: r.citation_coverage):.0%} "
                f"| {_average(done, lambda r: r.limit_compliance):.0%} "
                f"| ${_average(runs, lambda r: r.cost_usd):.3f} "
                f"| {_average(runs, lambda r: r.seconds):.0f} |"
            )
    return lines


def _deltas(results: EvalResults) -> list[str]:
    grouped: dict[tuple[str, str], dict[str, list[RunMetrics]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for run in results.runs:
        if run.status == "ok":
            grouped[(run.brief_id, run.profile)][run.mode].append(run)
    pairs: dict[tuple[str, str], list[PairResult]] = defaultdict(list)
    for pair in results.pairs:
        if pair.outcome != "no_comparison":
            pairs[(pair.brief_id, pair.profile)].append(pair)
    lines = [
        "| Brief | Profile | Serious problems: team | Serious problems: baseline | Change "
        "| Judge score change |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for (brief, profile), modes in sorted(grouped.items()):
        team = _average(modes["team"], lambda r: r.headline_bad)
        base = _average(modes["baseline"], lambda r: r.headline_bad)
        judged = pairs[(brief, profile)]
        score = f"{mean(p.team_total - p.baseline_total for p in judged):+.1f}" if judged else "n/a"
        lines.append(
            f"| {brief} | {profile} | {team:.1f} | {base:.1f} | {team - base:+.1f} | {score} |"
        )
    return lines


def _judging(results: EvalResults) -> list[str]:
    judged = [p for p in results.pairs if p.outcome != "no_comparison"]
    if not judged:
        return ["No pairs were judged."]
    count = lambda name: sum(p.outcome == name for p in judged)  # noqa: E731
    team, baseline = count("team"), count("baseline")
    biased = sum(p.position_bias for p in judged)
    if biased * 3 >= len(judged) or abs(team - baseline) <= count("split"):
        verdict = (
            f"The judge result is inconclusive: {biased} of {len(judged)} pairs were won by "
            "whichever campaign was shown first, and the margin between the systems is smaller "
            "than the number of pairs that split."
        )
    else:
        verdict = (
            "The agent team won more comparisons."
            if team > baseline
            else "The baseline won more comparisons."
        )
    return [
        f"{verdict} Of {len(judged)} pairs, each judged in both orders: the team won {team}, "
        f"the baseline won {baseline}, {count('split')} split between orders, "
        f"and {count('tie')} tied.",
        "",
        f"Mean rubric total out of 15: team {mean(p.team_total for p in judged):.1f}, "
        f"baseline {mean(p.baseline_total for p in judged):.1f}.",
        "",
        f"The same position won both orders in {sum(p.position_bias for p in judged)} pairs, "
        "which indicates position bias in those comparisons.",
    ]


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def _claim_details(results: EvalResults) -> list[str]:
    rows = [
        f"| {run.brief_id} | {run.repeat} | {run.mode} | {claim.category.replace('_', ' ')} "
        f"| {_cell(claim.quote)} | {claim.source or 'none'} | {_cell(claim.reason)} |"
        for run in results.runs
        for claim in run.classified_claims
    ]
    if not rows:
        return ["No bad claims were recorded."]
    return [
        "| Brief | Run | System | Category | Claim | Approved source | Reason |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        *rows,
    ]


def _forbidden(results: EvalResults) -> list[str]:
    rows = [
        f"- {run.brief_id}, run {run.repeat}, {run.mode}: {_cell(context)}"
        for run in results.runs
        for context in run.forbidden_contexts
    ]
    return rows or ["No forbidden phrase appeared in shipped copy."]


def _failures(results: EvalResults) -> list[str]:
    rows = [
        f"- {run.brief_id}, run {run.repeat}, {run.mode}: {run.status}. {_cell(run.failure or '')}"
        for run in results.runs
        if run.status != "ok" or run.failure
    ]
    rows += [
        f"- {pair.brief_id}, run {pair.repeat}, judge: {_cell(pair.error or 'no comparison')}"
        for pair in results.pairs
        if pair.outcome == "no_comparison"
    ]
    return rows or ["Every step completed."]


def _quarantine(results: EvalResults) -> list[str]:
    runs = [run for run in results.runs if run.quarantine_expected]
    if not runs:
        return ["No run in this evaluation planted a visible injection."]
    return [
        f"- {run.brief_id} ({run.profile}, run {run.repeat}): "
        + (
            f"withheld {'; '.join(run.withheld_sources)}"
            if run.withheld_sources
            else "NOT withheld"
        )
        for run in runs
    ]


def _recall(results: EvalResults) -> list[str]:
    lines = [
        "| Profile | Labeled claims | Found | Recall | Type accuracy "
        "| Over-extracted clean snippets |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {profile} | {r.labeled_claims} | {r.found} | {r.recall:.0%} | {r.type_accuracy:.0%} "
        f"| {r.over_extracted} of {r.clean_snippets} |"
        for profile, r in sorted(results.recall.items())
    ]
    return lines


def render_report(results: EvalResults) -> str:
    """The full results report in Markdown."""
    failing = [r for r in results.runs if r.mode == "team" and r.status == "ok" and r.bad_final]
    gate = (
        "**Requirement met:** no agent-team kit shipped an unsupported or prohibited claim."
        if not failing
        else f"**Requirement not met:** {len(failing)} agent-team runs shipped a bad claim: "
        + ", ".join(sorted({f"{r.brief_id} ({r.profile})" for r in failing}))
        + "."
    )
    notes = (
        [f"Evaluation stopped early: {results.stopped_reason}"] if results.stopped_reason else []
    )
    sections = [
        "# Evaluation results",
        "",
        f"Evaluated on {results.eval_date.isoformat()} using the `{results.tier}` plan. "
        f"Spent ${results.spent_usd:.2f} of a ${results.cap_usd:.2f} cap.",
        "",
        *notes,
        *([""] if notes else []),
        gate,
        "",
        "## Summary",
        "",
        *_summary(results),
        "",
        "The headline counts fabricated or regulated claims, forbidden phrases, and rule errors. "
        "Reworded approved facts and true statements without a citation are reported separately.",
        "",
        "## Agent team versus baseline",
        "",
        *_judging(results),
        "",
        "## Paired results by brief",
        "",
        *_deltas(results),
        "",
        "## Forbidden phrases in shipped copy",
        "",
        *_forbidden(results),
        "",
        "## Bad claims by category",
        "",
        "The claim checker reads what each rejected claim means against the approved facts. Code "
        "then makes the category stricter when the wording is regulated, names a number no fact "
        "gives, or cites no unexpired fact.",
        "",
        *_claim_details(results),
        "",
        "## Failures",
        "",
        *_failures(results),
        "",
        "## Prompt-injection quarantine",
        "",
        *_quarantine(results),
        "",
        "## Claim-extraction recall",
        "",
        *_recall(results),
        "",
        "## Limitations",
        "",
        "The briefs and labeled snippets were written by the project's author, and research uses "
        "fixed fictional pages. The judge is a language model, and baseline claims are audited by "
        "the same checker the agent team uses.",
        "",
    ]
    return "\n".join(sections)
