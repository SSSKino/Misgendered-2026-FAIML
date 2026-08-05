from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict

from llm_api import call_structured_json, get_default_model, get_default_temperature
from common_io import (
    build_parent_aggregate_json,
    build_setting_payload,
    infer_experiment_id,
    load_sample,
    normalize_prediction,
    resolve_path_with_fallback,
    write_json,
)

EXACT_PROMPT = r"""
You are a strict, conservative, evidence-based evaluator of ESG claims.

Use only the provided evidence fields as support.
The claim text is not evidence.
Do not use external knowledge, assumptions, industry conventions, unstated information, company identity, dataset patterns, sample IDs, notes, rationales, existing labels, or prior examples.

Evaluate whether the provided evidence substantively supports the claim as written.

Assign exactly one label:
- Fully Supported
- Partially Supported
- Suspected Greenwash

Substantive evidence

Substantive evidence means factual support found in the provided evidence fields.

Substantive evidence provides factual grounding for the claim. It is more than unsupported assertion, promotional language, aspiration, commitment, repetition, or general relevance to the same topic.

Substantive evidence may be qualitative or quantitative. It may include disclosed facts, measured values, extracted values, reported metrics, observed results, dates, quantities, rates, percentages, baselines, thresholds, targets, statuses, actions, outcomes, comparisons, limits, or other factual information contained in the evidence fields.

The evidence fields themselves are the evidence. Factual information in metric_name, extracted_value, value_unit, context_text, or any other provided evidence field may substantively support the claim.

A structured metric name, extracted value, unit, table entry, concise disclosure, or report sentence can be substantive evidence when it contains factual information that verifies the claim’s material meaning.

Evidence is not non-substantive merely because its wording resembles the claim. Similar wording does not remove evidential value when the evidence field contains a factual disclosure, extracted value, measured result, status, or concrete reported fact.

Evidence is non-substantive when it only repeats, affirms, paraphrases, or restates the claim’s conclusion without additional factual grounding.

Facts, numbers, outcomes, comparisons, qualifiers, implications, or conclusions that appear only in the claim text do not verify the claim.

The claim text may define what assertion, condition, threshold, comparison, baseline, or relationship must be evaluated, but it does not itself prove that assertion, condition, threshold, comparison, baseline, or relationship.

A claim-internal number, threshold, baseline, or comparison may define the meaning of the claim. Evidence can support the claim by providing factual values or facts that materially satisfy that asserted condition. However, when the claim-internal number, threshold, baseline, or comparison is itself a material factual assertion not supported by the evidence fields, support is incomplete.

Claim meaning

A claim must be evaluated according to its practical meaning as written.

The practical meaning of a claim is the factual meaning a reasonable reader would take from the claim, including its asserted result, scope, timeframe, magnitude, comparison, boundary, baseline, denominator, causation, effectiveness, achievement level, certainty, qualification, and stated or implied impact.

The central assertion is the main factual proposition expressed by the claim.

The decisive assertion is the part of the claim that gives the claim its main practical force. Without the decisive assertion, the claim would become materially different, weaker, narrower, less certain, less favorable, less comparative, less causal, less complete, or less outcome-based.

A material assertion is any element of the claim that changes its factual, quantitative, comparative, causal, temporal, qualitative, evaluative, outcome-based, or practical meaning.

A contextual element is wording that frames, emphasizes, introduces, or explains the claim without materially changing what the claim asserts.

A claim is evaluated as written, but support is assessed according to the claim’s materially load-bearing meaning rather than incidental wording.

A missing detail matters only when that detail changes the claim’s practical meaning. Missing raw data, methodology, source triangulation, definitions, sub-boundaries, operational details, or independent corroboration does not reduce support unless the claim’s material meaning depends on those details.

A wording element is material when removing it would materially weaken, narrow, qualify, or change the factual assertion. A wording element is contextual when it mainly provides emphasis, narrative framing, or background without changing the factual assertion.

Material alignment

Material alignment means that the evidence supports the same practical meaning expressed by the claim.

Material alignment concerns the relationship between what the claim asserts and what the evidence substantiates.

Material alignment includes alignment in factual result, scope, timeframe, magnitude, comparison, baseline, denominator, qualification, certainty, causation, effectiveness, achievement level, and practical implication when those elements are material to the claim.

Evidence for a related, narrower, weaker, approximate, secondary, partial, or different proposition is not the same as evidence for the claim as written.

Evidence that supports only a background fact, surrounding fact, associated fact, preparatory fact, proxy fact, or partial fact does not substantively support the claim unless that fact genuinely grounds the claim’s central assertion, decisive assertion, or a material part of them.

The strength of support depends on whether the evidence grounds the claim’s materially load-bearing meaning, not merely whether the evidence and claim share the same topic.

Label definitions

Fully Supported

Fully Supported describes a claim whose materially load-bearing practical meaning is directly and sufficiently verified by substantive evidence.

A Fully Supported claim has substantive evidence for its central assertion, decisive assertion, and material assertions.

The evidence supports the claim at the same strength, breadth, specificity, certainty, scope, timeframe, magnitude, comparison, causal meaning, achievement level, and practical implication expressed by the claim.

Fully Supported requires support for the claim as written, not merely support for a nearby, weaker, narrower, approximate, partial, related, secondary, or materially different version of the claim.

Fully Supported can apply when the evidence directly discloses factual information that matches the claim’s material meaning.

Fully Supported can apply when extracted values, reported metrics, units, table entries, or concise factual disclosures materially verify the claim, even if the surrounding text is brief or similar to the claim.

Fully Supported does not require additional raw data, methodology, independent corroboration, or external verification unless the claim’s material meaning depends on those elements.

Fully Supported can apply when the evidence provides factual values that materially satisfy a claim-defined condition, threshold, comparison, or direction of change.

Minor contextual, rhetorical, explanatory, introductory, or non-material wording does not prevent Fully Supported when the evidence verifies the claim’s materially load-bearing meaning.

Fully Supported does not describe claims whose support depends on unsupported assumption, unsupported inference, selective interpretation, unsupported expansion of scope, unsupported causal attribution, unsupported comparison, omission of material limiting evidence, or treatment of a partial evidential element as the whole claim.

Fully Supported does not describe claims where the evidence supports only effort, intention, activity, process, disclosure, policy existence, program existence, or general relevance while the claim materially asserts a verified result, outcome, impact, effectiveness, achievement, comparison, causation, threshold, or standard.

Partially Supported

Partially Supported describes a claim whose decisive assertion or a material part of its central assertion is genuinely grounded in substantive evidence, while the claim’s complete practical meaning is not fully verified.

A Partially Supported claim has real factual grounding in the evidence, but the support is incomplete in one or more material respects.

The evidence supports something that belongs to the claim’s own practical meaning, not merely something adjacent to the same topic.

Partially Supported applies where the evidence substantiates a meaningful limited version of the claim, and that limited version still grounds the claim’s central assertion, decisive assertion, or a material part of them.

The incompleteness may concern scope, timeframe, magnitude, comparison, baseline, denominator, certainty, qualification, causation, effectiveness, achievement level, outcome, standard, implication, or another material element.

Partially Supported includes claims where the evidence supports a material component of the claim but does not support the claim at the full strength, breadth, specificity, certainty, completeness, or favorability expressed.

Partially Supported includes claims where the main factual result is supported but a material cause, driver, attribution, explanation, comparison, scope, timeframe, or broader implication is not fully verified.

Partially Supported includes claims where the evidence supports concrete action, status, performance, implementation, or progress, but the claim adds a broader result, effect, achievement, comparison, impact, causal meaning, or favorable conclusion that is only partly grounded.

Partially Supported includes claims with comparative, leading, benchmark, or relative wording where the evidence provides substantive performance facts that ground a limited version of the claim, but does not fully verify the comparison, ranking, benchmark, comparison class, or relative position.

Partially Supported includes claims where the evidence supports a material factual condition related to the claim, while some other material condition remains unverified but does not defeat the supported part.

Partially Supported does not describe evidence that is empty, unavailable, placeholder-like, non-substantive, merely promotional, merely topic-related, or only a broad restatement of the claim.

Partially Supported does not describe a claim whose decisive assertion is ungrounded, contradicted, materially weakened, numerically inconsistent, defeated by limiting evidence, or materially stronger than the evidence supports.

Partially Supported does not describe a claim where the evidence supports only a background, surrounding, preparatory, proxy, secondary, substitute, or loosely related fact while leaving the claim’s decisive assertion unsupported.

Suspected Greenwash

Suspected Greenwash describes a claim whose decisive assertion is not meaningfully grounded in the provided evidence, or whose wording materially overstates what the evidence substantiates.

Suspected Greenwash describes evidential mismatch between the claim’s practical meaning and the provided evidence.

In Suspected Greenwash cases, the evidence may be factual and relevant to the general topic, but it does not substantively verify the claim’s main practical force.

Suspected Greenwash includes claims where the evidence substantiates only a related, narrower, weaker, approximate, partial, secondary, preparatory, proxy, substitute, background, or topic-related proposition while leaving the decisive assertion unverified.

Suspected Greenwash includes claims where the claim presents a materially stronger, broader, more certain, more complete, more causal, more comparative, more outcome-based, more achievement-based, or more favorable meaning than the evidence supports.

Suspected Greenwash includes claims where the decisive assertion is contradicted, materially weakened, or defeated by the evidence.

Suspected Greenwash includes claims where the evidence supports an input, activity, intention, process, disclosure, status, partial metric, or general effort, but the claim’s practical meaning asserts a result, effect, achievement, comparison, causation, outcome, standard, or broader favorable conclusion that is not substantively verified.

Suspected Greenwash includes claims where a numerical, comparative, threshold-based, causal, absolute, universal, exact, outcome-based, standard-based, or achievement-based assertion is not materially verified by the evidence.

Suspected Greenwash includes claims where limiting facts in the evidence materially change the claim’s practical meaning or make the claim materially less supported than its wording suggests.

Suspected Greenwash includes claims where the evidence repeats a favorable conclusion but lacks factual grounding for that conclusion, or where factual information in the evidence limits, weakens, or contradicts that conclusion.

Suspected Greenwash is not limited to cases with no evidence. It also includes cases where the evidence is real but substantively misaligned with the claim, or where supported evidence does not ground the claim’s decisive assertion.

Suspected Greenwash does not describe a claim whose decisive assertion is genuinely grounded in substantive evidence but remains incomplete, narrower, weaker, indirect, limited, or insufficiently specific. Such cases belong to Partially Supported.

Suspected Greenwash does not require proof of intentional deception. It means only that the provided evidence does not meaningfully verify the claim as written, or that the claim’s wording is materially stronger than the evidence supports.

Conceptual boundaries

The difference between Fully Supported and Partially Supported is completeness of material support.

Fully Supported means the evidence verifies the claim’s materially load-bearing practical meaning in all material respects.

Partially Supported means the evidence genuinely grounds the claim’s decisive assertion or a material part of the central assertion, but does not verify the claim’s complete practical meaning in all material respects.

The difference between Partially Supported and Suspected Greenwash is whether the evidence meaningfully grounds the claim’s decisive assertion.

Partially Supported requires substantive support for the decisive assertion or for a material part of the central assertion.

Suspected Greenwash applies where the decisive assertion is ungrounded, contradicted, defeated, or materially overstated, even if the evidence supports some related, narrower, weaker, secondary, proxy, preparatory, or topic-related fact.

A claim is not Partially Supported merely because the evidence is generally relevant, ESG-related, partially favorable, or connected to the same broad subject.

A claim is not Suspected Greenwash merely because the evidence lacks full support, if the evidence still substantively grounds the decisive assertion or a material part of the central assertion.

For comparative or qualitative claims, the absence of complete comparative proof prevents Fully Supported when the comparison is material. It does not by itself require Suspected Greenwash if the evidence substantively grounds a meaningful limited version of the comparative or qualitative assertion.

For outcome, impact, achievement, or effectiveness claims, evidence of related activity or effort is insufficient unless it substantively grounds the claimed result, effect, achievement, or practical conclusion.

For absolute, universal, exact, or threshold-based claims, evidence of exceptions, shortfalls, incompleteness, or materially weaker performance can defeat meaningful support when the absolute, universal, exact, or threshold-based meaning is material to the claim.

Numerical meaning

Numerical, percentage, threshold, target, comparison, and exact achievement claims require material numerical alignment with the evidence.

A numerical claim is Fully Supported only when the evidence verifies the claimed number, direction, magnitude, threshold, denominator, baseline, timeframe, and scope in all material respects.

Approximate numerical language allows reasonable rounding, but not a materially different value.

A claim that states or implies a threshold, target, milestone, or achievement is not meaningfully verified when the evidence shows that the threshold, target, milestone, or achievement is missed, incomplete, pending, materially lower, or otherwise not met.

Where the evidence provides concrete values that match or materially satisfy the claim’s numerical meaning, the evidence can be substantive even without the underlying raw calculation method.

Output requirements:
Return only one valid JSON object.
No markdown.
No extra text.
Exactly two keys:
- "label"
- "reason"

The label must be exactly one of:
- "Fully Supported"
- "Partially Supported"
- "Suspected Greenwash"

The reason must:
- identify the claim’s central assertion or decisive assertion
- state whether the evidence substantiates any material part of the claim
- state what is missing, limited, weakened, overstated, contradicted, numerically inconsistent, or not fully verified
- include numerical verification when the claim contains numbers, comparisons, thresholds, reductions, increases, percentages, or exact achievements
- rely only on the provided evidence fields
- avoid sample IDs, company patterns, dataset patterns, previous labels, hidden assumptions, and evaluation strategy language

Return format:
{"label":"...","reason":"..."}

Now evaluate the following claim and evidence:

""".strip()

OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "label": {
            "type": "string",
            "enum": ["Fully Supported", "Partially Supported", "Suspected Greenwash"],
        },
        "reason": {"type": "string"},
    },
    "required": ["label", "reason"],
}


def call_api(*, experiment_name: str, raw_fallback_name: str, model: str, payload: Dict[str, Any], temperature: float) -> Dict[str, Any]:
    return call_structured_json(
        instructions=EXACT_PROMPT,
        payload=payload,
        schema_name=f"{experiment_name}_claim_support_3class",
        schema_description="Three-class ESG claim support result with label and reason",
        output_schema=OUTPUT_SCHEMA,
        raw_fallback_name=raw_fallback_name,
        model=model,
        temperature=temperature,
    )


def run_single_evaluation(*, experiment_name: str, setting_name: str, raw_fallback_name: str) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sample", help="Path to a single sample JSON file")
    parser.add_argument("--out", default=f"{experiment_name}.json", help=f"Output file (default: {experiment_name}.json)")
    parser.add_argument("--skip-parent-aggregate", action="store_true", help="Do not rebuild the parent summary JSON after writing the single result")
    parser.add_argument("--model", default=get_default_model(), help=f"Model name (default from .env/environment: {get_default_model()})")
    parser.add_argument("--temperature", type=float, default=get_default_temperature(), help=f"Temperature (default from .env/environment: {get_default_temperature()})")
    args = parser.parse_args()

    sample_path = resolve_path_with_fallback(args.sample)
    out_path = resolve_path_with_fallback(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sample = load_sample(sample_path)
    payload = build_setting_payload(sample, setting_name=setting_name)
    model_json = call_api(
        experiment_name=experiment_name,
        raw_fallback_name=raw_fallback_name,
        model=args.model,
        payload=payload,
        temperature=args.temperature,
    )
    final_json = normalize_prediction(
        model_json,
        sample=sample,
        sample_path=sample_path,
        experiment_name=experiment_name,
        setting_name=setting_name,
        model_name=args.model,
        temperature=args.temperature,
        input_payload=payload,
    )
    write_json(out_path, final_json)
    if not args.skip_parent_aggregate:
        build_parent_aggregate_json(
            out_path,
            meta={
                "experiment_id": infer_experiment_id(experiment_name=experiment_name, setting_name=setting_name),
                "experiment_name": experiment_name,
                "setting_name": setting_name,
            },
        )
    print(f"[DONE] {experiment_name}")
