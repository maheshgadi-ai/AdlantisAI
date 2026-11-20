# Decisions

Architecture decision records, grouped by topic. Each one gives the context, the decision, and its consequences.

| Topic | Decisions |
| --- | --- |
| [Foundations](#foundations) | 4 |
| [Models and cost](#models-and-cost) | 4 |
| [Claims and rules](#claims-and-rules) | 7 |
| [Research and untrusted content](#research-and-untrusted-content) | 8 |
| [Verification and revision](#verification-and-revision) | 8 |
| [Packaging and sign-off](#packaging-and-sign-off) | 3 |
| [Interfaces and deployment](#interfaces-and-deployment) | 3 |
| [Evaluation](#evaluation) | 4 |

## Foundations

### Shared modules

**Context.** Provider access, configuration, tracing, and research tools are general infrastructure that already exists in the author's own projects.

**Decision.** These modules are copied and adapted to the `adlantis` package.

| Source | Modules |
| --- | --- |
| InboxternAI | `llm/` (providers, router, pricing, usage, prompt caching), `config/` (settings, model catalog, deprecation guard, profile loading), `observability/` (Langfuse wrapper, JSON logging), `prompts/` loader, `agents/base.py`, `tests/test_architecture.py` |
| QuillvaneAI | `tools/web_search.py`, `tools/fetch_url.py`, `tools/http.py`, `tools/extract.py`, `tools/cache.py`, `tools/source_quality.py`, `tools/base.py`, `tools/registry.py`, `schemas/evidence.py`, `schemas/quality.py`, `schemas/titles.py`, `schemas/ledger.py` |

**Consequences.** The issue ledger is rewritten around claims: every open or regressed issue blocks its asset, and a resolved problem that is reported again becomes regressed.

### Rules are a separate layer

**Context.** The rules must win over model judgments, so they cannot depend on any model.

**Decision.** `rules` sits beside `llm` and `tools`, and imports only `schemas` and `config`.

**Consequences.** An architecture test guarantees that the rules stay deterministic.

### Evals sit above the orchestrator

**Context.** Evals must run complete campaigns to measure them.

**Decision.** `evals` may import `orchestrator`, and never the reverse.

**Consequences.** Pipeline code stays free of evaluation concerns.

### Sync providers with threaded concurrency

**Context.** The provider layer is synchronous, and independent work should overlap.

**Decision.** `BaseAgent.arun` runs an agent in a worker thread through `asyncio.to_thread`. Usage totals and the router are thread-safe.

**Consequences.** Orchestration uses asyncio without a second provider implementation.

## Models and cost

### Routing rules are enforced at startup

**Context.** Environment overrides can change any role's model, so tests of the shipped profiles alone cannot protect a running system.

**Decision.** `config/role_rules.py` validates the resolved routing whenever a router is built from settings. The router also rejects unknown roles.

**Consequences.** A misconfigured deployment fails immediately instead of letting a provider check its own copy.

### Budget profile models

**Context.** The budget profile should lower cost without weakening verification.

**Decision.** The copywriter uses the lowest-priced OpenAI model documented for natural writing. Claim checking stays on a strong Anthropic model at high effort. The judge uses a stronger model than the copywriter.

**Consequences.** Savings come from drafting and research, not from the checks that protect claims.

### The budget cap holds money before each call

**Context.** Adding up costs after each call cannot stop the call that passes the cap, and concurrent calls can all start at once.

**Decision.** Each billed call first reserves its maximum cost, based on its input size, output limit, and configured price. Calls wait while reservations in flight may free room. A call is refused unsent when nothing in flight can make room, and a model with no configured price is refused under a cap.

**Consequences.** Near the cap, work slows down and then stops cleanly, and unfinished assets become gaps. Estimated reservations are deliberately high, so a run can stop with some budget unspent.

### Image generation uses GPT-Image-2.6 Flare

**Context.** OpenAI has retired DALL-E and GPT Image 1 and has scheduled shutdowns for GPT Image 1 Mini, 1.5, and 2. GPT-Image-2.6 Sunburst and Flare are the recommended replacements at the same token prices.

**Decision.** The model lives in `config/image_models.yaml`, and the loader refuses any model on the deprecations list. Generation stays off unless `ENABLE_IMAGES=true`. Search ads get no image because the channel is text only.

**Consequences.** OpenAI publishes no per-image cost for this model, so each image reserves a fixed amount and is charged from reported usage.

## Claims and rules

### Regulated claims require verbatim approved wording

**Context.** A citation alone proves little. A fact reading "Best Espresso, 2026 Cup Awards" must not license "the best coffee in the world".

**Decision.** A regulated claim is exempt only when its matched text lies inside an approved wording of a cited, unexpired fact of the same claim type. Prices are the one exception: a bare amount may be restated when its value and currency match the cited fact.

**Consequences.** Copy has less freedom around regulated claims, and every exemption can be traced to approved text. Offers cannot lose their conditions, because "Free shipping" does not match "Free shipping on orders over $40".

### The rules engine favors false alarms

**Context.** A blocked sentence costs one revision. A shipped violation costs far more.

**Decision.** Wording rules match conservatively, and unknown fields and references fail closed. Guards exist only for common harmless phrases such as "best before" and "carbon fork".

**Consequences.** Some harmless copy is sent back for revision. Rules recognize wording, not meaning, so a claim phrased in unlisted words is left to the claim checker.

### Brands can ban only detectable claim types

**Context.** Product facts and uncategorized claims have no reliable wording signature.

**Decision.** `banned_claim_types` rejects `product_fact` and `other` when the brand kit loads.

**Consequences.** A brand cannot configure a ban that would silently never fire.

### Channel limits record their source and severity

**Context.** Some limits are enforced by platforms, some are display guidance, and some are editorial choices.

**Decision.** Each limit in `config/channel_limits.yaml` records its severity, source type, reference, and whether the source is a third party. Platform rejection limits are errors and block the asset. Truncation guidelines and editorial limits are warnings: they appear in the kit and never block. Instagram and LinkedIn have a hard post cap that blocks and a "see more" point that warns. Both figures are marked as third-party because they could not be confirmed from official pages.

**Consequences.** Copy is blocked only when a platform would refuse it, while the copywriter still aims within every limit.

### Names are not claims

**Context.** A brand or product name cannot be shown true or false, yet a cited name would otherwise need a verdict and could block an asset.

**Decision.** Text that is only a name from `brand.yaml` or `product.yaml`, alone or after a plain invitation such as "Meet", is not treated as a claim. Any further word keeps the statement under review. Search ad headlines must name the product, and revisions cannot remove it.

**Consequences.** Brands list every accepted name variant as an alias. Rule violations inside a name still block the asset.

### Glossary definitions are approved wording

**Context.** Brands need to explain terms, but a definition written by a model is an unsourced factual statement.

**Decision.** `brand.yaml` can hold glossary entries. An entry used word for word, as `Term: definition`, needs no citation. Any rewording is treated as an ordinary claim. The checker must still accept the entry, so code never upgrades a verdict.

**Consequences.** Definitions read the same everywhere, and long entries do not fit short channels such as search ads.

### Channel plans may paraphrase approved facts

**Context.** Channel plans are internal notes on how a channel will be used, and requiring the exact wording of a fact in planning prose caused revisions without protecting anything a customer reads.

**Decision.** A channel plan may reword a cited fact when the checker judges the statement supported and its supporting passage appears in the cited source. Exact wording stays required for assets, key messages, and glossary terms, and for numbers and regulated claims everywhere, including channel plans. Kits label channel plans "Internal planning, not for publication."

**Consequences.** Plans read more naturally and need fewer revisions. Any plan statement with a number or a regulated claim is still held to the approved wording.

## Research and untrusted content

### Address checks on fetched URLs

**Context.** The model chooses which URLs to read, which creates a server-side request forgery risk.

**Decision.** Every hop must resolve only to public addresses before it is requested.

**Consequences.** The address is resolved again when the connection opens, so a host that changes its DNS answer between the two lookups is not covered. Deployments that need that guarantee should also restrict egress at the network layer.

### Web content is quarantined on suspicion

**Context.** A marketing system that reads the open web will meet pages written to manipulate it. Filtering suspicious sentences would still pass the rest of a hostile page to the model.

**Decision.** A source with any instruction-like signal is withheld in full, kept for audit, and cannot be cited.

**Consequences.** An ordinary page that happens to resemble an instruction is lost as a source. Detection covers English wording only, so it is one layer among several and no guarantee depends on it alone.

### The researcher cannot act on what it reads

**Context.** Prompt injection cannot be fully prevented by asking a model to resist it.

**Decision.** Safety is enforced in code around the model. It can search, read URLs that search returned, and submit findings. It never receives the fact sheet, and every finding must quote a usable source.

**Consequences.** A fooled model can waste its research budget, but it cannot change facts, reach an attacker's URL, or introduce an ungrounded finding.

### Hidden text is detected without a browser

**Context.** Determining what a reader sees exactly requires rendering the page.

**Decision.** Extraction removes text hidden by attributes, inline styles, simple stylesheet rules, and colors matching the background.

**Consequences.** Hiding techniques that depend on complex CSS or scripts can survive extraction, and later layers treat that text as untrusted.

### Forms are read only when they hold the page

**Context.** Forms are usually page chrome, but some site platforms wrap the entire page in a single form.

**Decision.** The extractor skips forms unless the page has almost no text outside them. Hidden-text removal and chrome removal apply either way.

**Consequences.** Those sites become readable as sources. Sites that refuse automated readers are left alone, and their search excerpts remain available.

### Detector false positives are measured offline

**Context.** Quarantining a whole page on suspicion has a cost, and live runs rarely show how often it happens.

**Decision.** `evals/data/benign_pages.yaml` holds harmless pages written in imperative marketing and how-to language. A test pins exactly which pages are flagged, so the rate cannot rise unnoticed.

**Consequences.** Patterns that also match credit lines and articles about AI stay visible as known trade-offs of favoring safety.

### Web evidence cannot support regulated claims

**Context.** Health, environmental, superlative, pricing, and testimonial claims carry the most legal risk, and web pages can be written by anyone.

**Decision.** These claims require an approved fact of the same type.

**Consequences.** Research can inform a campaign's direction but never licenses a regulated claim.

### Research shapes strategy, not customer copy

**Context.** Survey figures in an ad can read as interruptions, and the evaluation judge rated such copy lower. Research is most useful for deciding who to speak to and what to lead with.

**Decision.** Market research informs the strategy and targeting. Customer-facing copy does not quote survey statistics or research findings unless the product brief sets `quote_research: true`.

**Consequences.** Copy stays focused on approved product facts. This is guidance to the copywriter, and the claim checker still verifies any research statement that appears.

## Verification and revision

### Model verdicts can only be made stricter by code

**Context.** A claim checker can be wrong, and a "supported" verdict is the one mistake that ships.

**Decision.** `rules/claim_gate.py` re-tests every supported verdict against the cited source and overrides it when the proof fails. Code never upgrades a verdict.

**Consequences.** Some true claims are sent back when the checker quotes its proof imprecisely. In exchange, no claim ships on a model's word alone.

### Every section of a kit is verified

**Context.** Checking only published copy leaves the strategy and image prompts free to state things no source supports, and a reviewer signs off on the whole kit.

**Decision.** Each strategy statement and image prompt passes through the claim checker, code gate, and rules engine. The strategy is verified before any copy is written from it. An unproven key message or channel plan is removed and listed as a gap. An unproven positioning or concept stops the run. An unproven image prompt is dropped. The packager and the sign-off both refuse a kit containing a statement without a passing check.

**Consequences.** Verification adds checker calls to each run. Statements of intent, audience, and creative direction are not treated as claims. Research gaps and issue descriptions are records about the run, so they are not verified as campaign claims.

### Revisions are exact replacements

**Context.** Asking a model to rewrite failing copy tends to disturb passages that had already passed.

**Decision.** A revision is a list of exact passage replacements tied to open issue IDs, limited to 300 characters each and applied by code.

**Consequences.** Verified copy stays intact. An issue that needs a broad rewrite ends as a gap instead.

### Citations follow their statements through edits

**Context.** A targeted edit often trims a cited sentence. Matching citations by their original text would drop the source of the words that remain, and a sound statement would then fail review.

**Decision.** `orchestrator/revision.py` rewrites a citation to the statement's new text and keeps its sources. A statement replaced in full does not keep them, because they proved the old text.

**Consequences.** Trimmed copy stays traceable, and the claim checker still tests every carried citation against the revised words.

### The best version is the one with the fewest open problems

**Context.** A revision can make an asset worse.

**Decision.** A version with more problems than the best so far is discarded, and its check resolves nothing in the ledger. On a tie the newer version is kept, so revisions can make progress.

**Consequences.** Bad revisions never compound, and only a version with no blocking problems can ship.

### Gaps do not carry failed copy

**Context.** Anything attached to a kit can be copied out of it.

**Decision.** A gap records the asset ID, channel, reason, and issue IDs, but not the asset's text.

**Consequences.** Failed copy cannot leak through the kit. The issue ledger keeps short quotes for audit.

### Dropped work is always reported

**Context.** A variant that fails validation or a page that cannot be read should never disappear silently.

**Decision.** Each dropped variant becomes a gap with its reason, in campaign and baseline runs. Failed tool calls are written to `run_log.jsonl` with their cause, leaving out any text quoted from the remote server.

**Consequences.** Gaps can list variants even when the channel still ships other assets.

### Image checks understand negation

**Context.** Prompts often say what must not appear, such as "no logos", and treating those words as a request rejects safe prompts.

**Decision.** Code removes lists that a negation rules out before checking a prompt. It keeps anything uncertain, so "no text, with a logo on the cup" and "do not omit logos" are still refused. Banned words are refused even when negated.

**Consequences.** Unusual phrasing can still cause a false alarm, which leaves an asset without an image prompt.

## Packaging and sign-off

### Sign-off is bound to the content

**Context.** An approval means little if the kit can change afterward or if automation can grant it.

**Decision.** Approval records a fingerprint of the kit and needs a person to type the run name. There is no flag to skip that step, and baseline kits can never be approved.

**Consequences.** Editing a packaged kit requires a new run. Fingerprints detect changes but are not cryptographic signatures.

### Baseline runs are for evaluation only

**Context.** Comparing the agent team with a single prompt needs a fair baseline that is never mistaken for verified work.

**Decision.** The baseline makes one call on the copywriter's model, with no research, claim checker, or revision. Rule findings are recorded, and the kit is marked unverified.

**Consequences.** A baseline kit can be read and exported but never approved.

### The sample campaign omits raw research

**Context.** A saved campaign supports the keyless demo, and traceable sourcing is the point of the product. Raw research, however, holds long excerpts from third-party websites.

**Decision.** Brands, products, competitors, people, and logos in campaign content are fictional. Real publishers may appear as cited research sources. `examples/sample-campaign/` stores the strategy, copy, verdicts, issue ledger, and cost record of a live run, and the raw research file stays out of the repository.

**Consequences.** Market statements and a checker's stated reasons can name the publisher behind them. Evidence IDs in the sample have no matching source records.

## Interfaces and deployment

### The app keeps logic out of the page

**Context.** Streamlit pages rerun from the top on every interaction, which makes logic inside them hard to test.

**Decision.** `interfaces/app_support.py` holds the tables, input parsing, and key checks as plain functions. The page only lays them out, and runs a campaign in a worker thread that streams run-log events to a live timeline.

**Consequences.** Most of the app is tested without a browser, and the page itself is tested headlessly.

### The demo needs no API keys

**Context.** People evaluating the project need to see a finished kit without creating provider accounts or spending money.

**Decision.** `adlantis demo` opens an approved sample campaign in the app, read-only. The sample ships inside the package, and the demo hides the campaign form and sign-off.

**Consequences.** The demo shows a real run's output, but it cannot start a new run.

### Containers bind to localhost and get keys only when they need them

**Context.** A container that publishes on every interface, or carries keys it does not use, widens the attack surface for no benefit.

**Decision.** The image runs as a non-root user with no new privileges. Compose publishes ports on 127.0.0.1 only. The demo service receives no keys, and the app service reads them from the environment at start. `.env` is excluded from the build.

**Consequences.** Reaching the app from another machine needs a deliberate change, such as a reverse proxy with authentication.

## Evaluation

### Evaluations use a fixed fictional web

**Context.** Live search results change from day to day, which would make runs hard to compare, and adversarial pages need to appear on demand.

**Decision.** Evaluations serve fixed fictional pages through the real extraction, quarantine, and citation code. Planted pages test visible and hidden prompt injections. Outputs go to a scratch folder.

**Consequences.** Results are repeatable and searches cost nothing, but they do not measure how the researcher handles the open web.

### The baseline is audited by the same claim checker

**Context.** Comparing claim safety needs one measure across both systems, and the baseline has no review step of its own.

**Decision.** The claim checker audits every baseline asset after it is written. The audit does not change the baseline's copy. Judging is blind: the judge sees customer-facing text only, in both orders.

**Consequences.** Both systems are scored on the same scale, and a checker's blind spots affect both. Results are reported whichever system they favor.

### Evaluation headlines separate invention from wording problems

**Context.** A checker can reject a true statement because it rewords an approved fact or lacks a citation. Counting that the same way as an invented claim overstates the risk.

**Decision.** The claim checker reads each rejected claim against the approved facts and decides whether its meaning is stated by an approved fact, or whether it is only a call to action. Code makes the result stricter when the wording is regulated, names a number no cited fact gives, or names no unexpired fact. Claims are then sorted into fabricated or regulated claims, paraphrased approved facts, uncited but true statements, and calls to action, which are not claims. The headline counts only the first group, plus forbidden phrases and rule errors. The other two are reported separately. The requirement that the agent team ships no unsupported or prohibited claim still covers all three.

**Consequences.** Reports show how serious each failure is. The sort is a model judgment bounded by code, and every claim is listed with its reason so a reviewer can check it. Re-scoring saved results bills one checker call per run with rejected claims.

### Evaluation failures are recorded, never counted as clean

**Context.** A provider outage can fail runs and claim audits partway through an evaluation, and a failed audit can look like a baseline with no claims.

**Decision.** Every failed run, claim audit, triage, and judging step records its reason in the results. A baseline whose audit fails is marked unaudited and left out of claim counts. `adlantis eval complete` re-runs failed agent-team runs and judges them against the baselines already saved.

**Consequences.** Reports list every failure. Totals cover only the runs that were fully measured.
