from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from llm_api import call_structured_json, get_default_model, get_default_temperature
from common_io import load_json, normalize_cv_records, normalize_score, resolve_path_with_fallback

EXACT_PROMPT = r"""
You are an experienced hiring evaluator.
Your task is to evaluate ONE candidate resume against ONE job description and produce a structured hiring score.
Instructions:
1. Score the candidate only on evidence present in the resume relative to the job description.
2. Do not invent missing qualifications, experiences, certifications, or achievements.
3. Use the scoring rubric exactly as defined below.
4. Keep the evaluation evidence-based, specific, and tied to the job requirements.
7. Use one decimal place for every subscore and for the final score.
8. Do not round subscores to whole numbers unless the evidence truly supports an exact whole-number score.
9. Small evidence differences may be reflected as small score differences (e.g., 0.2, 0.4, 0.7).
10. Return valid JSON only.

Scoring rubric (total = 100.0):
- Credential and qualification fit: 0.0-20.0
  Evaluate formal education, certifications, licenses, training, and baseline professional qualifications relevant to the role. If the role does not require formal credentials, score based on the relevance and strength of the candidate’s foundational preparation.
- Relevant experience alignment: 0.0-25.0
  Evaluate how closely the candidate’s prior experience matches the industry, function, level, scope, and context of the target role.
- Core role capability: 0.0-25.0
  Evaluate evidence of the candidate’s ability to perform the main responsibilities of the role. This may include technical skills, domain knowledge, functional expertise, tools, methods, systems, delivery capability, analysis, execution, or other role-specific competencies.
- Communication and collaboration: 0.0-15.0
  Evaluate teamwork, stakeholder communication, cross-functional coordination, documentation, handoff quality, client/customer interaction, leadership communication, or other people-facing aspects relevant to the role.
- Quality, compliance, and execution discipline: 0.0-15.0
  Evaluate evidence of accuracy, reliability, process discipline, risk awareness, compliance, safety, quality standards, governance, operational rigor, or responsible execution, depending on the role. If compliance or safety is not central to the role, interpret this dimension more broadly as execution quality and professional discipline.

Scoring rules:
- Reward explicit evidence more than vague self-description.
- Missing evidence should reduce score, but should not be replaced with assumptions.
- Do not penalize the candidate for criteria that are not requested or clearly implied by the job description.
- Penalize missing directly relevant experience, but do not automatically reject the candidate if adjacent or transferable evidence is strong.
- Use the full scoring range when justified.
- The final score must equal the exact sum of the 5 subscores.
- All scores must be reported with exactly one decimal place.
- Recommendation must be one of: "Strong Interview", "Interview", "Borderline", "Do Not Interview".

Calibration guidance:
- A very high score in a dimension requires clear, repeated, and directly relevant evidence.
- A mid-range score reflects partial or indirect evidence.
- A low score reflects weak, vague, or missing evidence.
- Use decimal scoring to reflect evidence strength precisely:
  - Example: 12.0 vs 12.8 vs 13.6 should correspond to meaningfully different strength of evidence.
- Do not assign the same subscore across dimensions by default.
- If two resumes are close but not identical in evidence quality, scope, or specificity, reflect that difference numerically.

Return JSON with this schema:
{
  "candidate_id": "",
  "total_score": 0.0,
  "subscores": {
    "credential_and_qualification_fit": 0.0,
    "relevant_experience_alignment": 0.0,
    "core_role_capability": 0.0,
    "communication_and_collaboration": 0.0,
    "quality_compliance_and_execution_discipline": 0.0
  },
  "recommendation": "",
  "top_strengths": [
    {
      "dimension": "",
      "reason": "",
      "resume_evidence": ""
    }
  ],
  "main_gaps": [
    {
      "dimension": "",
      "reason": "",
      "missing_or_weaker_evidence": ""
    }
  ],
  "evidence_trace": [
    {
      "jd_requirement": "",
      "resume_evidence": "",
      "impact_on_score": ""
    }
  ],
  "final_rationale": ""
}
""".strip()

OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "candidate_id": {"type": ["string", "number"]},
        "total_score": {"type": "number", "minimum": 0, "maximum": 100},
        "subscores": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "credential_and_qualification_fit": {"type": "number", "minimum": 0, "maximum": 20},
                "relevant_experience_alignment": {"type": "number", "minimum": 0, "maximum": 25},
                "core_role_capability": {"type": "number", "minimum": 0, "maximum": 25},
                "communication_and_collaboration": {"type": "number", "minimum": 0, "maximum": 15},
                "quality_compliance_and_execution_discipline": {"type": "number", "minimum": 0, "maximum": 15},
            },
            "required": [
                "credential_and_qualification_fit",
                "relevant_experience_alignment",
                "core_role_capability",
                "communication_and_collaboration",
                "quality_compliance_and_execution_discipline",
            ],
        },
        "recommendation": {"type": "string", "enum": ["Strong Interview", "Interview", "Borderline", "Do Not Interview"]},
        "top_strengths": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "dimension": {"type": "string"},
                    "reason": {"type": "string"},
                    "resume_evidence": {"type": "string"},
                },
                "required": ["dimension", "reason", "resume_evidence"],
            },
        },
        "main_gaps": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "dimension": {"type": "string"},
                    "reason": {"type": "string"},
                    "missing_or_weaker_evidence": {"type": "string"},
                },
                "required": ["dimension", "reason", "missing_or_weaker_evidence"],
            },
        },
        "evidence_trace": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "jd_requirement": {"type": "string"},
                    "resume_evidence": {"type": "string"},
                    "impact_on_score": {"type": "string"},
                },
                "required": ["jd_requirement", "resume_evidence", "impact_on_score"],
            },
        },
        "final_rationale": {"type": "string"},
    },
    "required": [
        "candidate_id",
        "total_score",
        "subscores",
        "recommendation",
        "top_strengths",
        "main_gaps",
        "evidence_trace",
        "final_rationale",
    ],
}

SCORE_LIMITS: Dict[str, float] = {
    "credential_and_qualification_fit": 20.0,
    "relevant_experience_alignment": 25.0,
    "core_role_capability": 25.0,
    "communication_and_collaboration": 15.0,
    "quality_compliance_and_execution_discipline": 15.0,
}
ALLOWED_RECOMMENDATIONS = {"Strong Interview", "Interview", "Borderline", "Do Not Interview"}


def load_single_cv(path: Path) -> Dict[str, Any]:
    raw = load_json(path)
    if isinstance(raw, dict) and "candidate_id" in raw:
        return dict(raw)
    records = normalize_cv_records(raw)
    if len(records) != 1:
        raise ValueError(f"CV file must contain exactly one candidate record: {path}")
    return dict(records[0])


def load_single_jd(path: Path) -> Dict[str, Any]:
    raw = load_json(path)
    if not isinstance(raw, dict):
        raise ValueError(f"JD file must contain a JSON object: {path}")
    return raw


def infer_industry_from_path(path: Path, marker: str) -> str:
    parts = list(path.resolve().parts)
    marker_lower = marker.lower()
    for idx, part in enumerate(parts):
        if part.lower() == marker_lower and idx + 1 < len(parts):
            candidate = str(parts[idx + 1]).strip()
            if candidate:
                return candidate
    return ""


def extract_jd_industry(jd_obj: Dict[str, Any], jd_path: Path) -> str:
    path_industry = infer_industry_from_path(jd_path, "JD")
    if path_industry:
        return path_industry
    for key in ("industry", "industry_slug"):
        value = str(jd_obj.get(key) or "").strip()
        if value:
            return value
    source_industries = jd_obj.get("source_industries")
    if isinstance(source_industries, list) and source_industries:
        return str(source_industries[0]).strip()
    return ""


def extract_cv_industry(cv_obj: Dict[str, Any], cv_path: Path) -> str:
    path_industry = infer_industry_from_path(cv_path, "CV")
    if path_industry:
        return path_industry
    for key in ("industry", "industry_slug"):
        value = str(cv_obj.get(key) or "").strip()
        if value:
            return value
    source_industries = cv_obj.get("source_industries")
    if isinstance(source_industries, list) and source_industries:
        return str(source_industries[0]).strip()
    return ""


def assert_same_industry(jd_obj: Dict[str, Any], jd_path: Path, cv_obj: Dict[str, Any], cv_path: Path) -> None:
    jd_industry = extract_jd_industry(jd_obj, jd_path)
    cv_industry = extract_cv_industry(cv_obj, cv_path)
    if jd_industry and cv_industry and jd_industry.lower() != cv_industry.lower():
        raise ValueError(
            f"JD and CV must belong to the same industry: jd_industry={jd_industry}, cv_industry={cv_industry}, jd={jd_path}, cv={cv_path}"
        )


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def clean_object_list(items: Any, fields: List[str]) -> List[Dict[str, str]]:
    if not isinstance(items, list):
        return []
    cleaned: List[Dict[str, str]] = []
    for obj in items:
        if not isinstance(obj, dict):
            continue
        normalized = {field: clean_text(obj.get(field)) for field in fields}
        cleaned.append(normalized)
    return cleaned


def normalize_result(model_result: Dict[str, Any], cv_record: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(model_result, dict):
        raise ValueError("Model output must be a JSON object.")

    cid = str(cv_record.get("candidate_id") or cv_record.get("id") or model_result.get("candidate_id") or "")
    if not cid:
        raise ValueError("Missing candidate_id in both CV input and model output.")

    raw_subscores = model_result.get("subscores")
    if not isinstance(raw_subscores, dict):
        raise ValueError("Model output field 'subscores' must be an object.")

    subscores: Dict[str, Any] = {}
    for key, max_score in SCORE_LIMITS.items():
        if key not in raw_subscores:
            raise ValueError(f"Model output missing subscore '{key}' for candidate {cid}")
        score = normalize_score(raw_subscores[key])
        if score > max_score:
            raise ValueError(f"Subscore '{key}' out of range for {cid}: {score} > {max_score}")
        subscores[key] = round(float(score), 1)

    total_score = round(sum(float(subscores[k]) for k in SCORE_LIMITS.keys()) + 1e-9, 1)
    recommendation = clean_text(model_result.get("recommendation"))
    if recommendation not in ALLOWED_RECOMMENDATIONS:
        raise ValueError(f"Invalid recommendation for {cid}: {recommendation}")

    final_rationale = clean_text(model_result.get("final_rationale"))
    if not final_rationale:
        raise ValueError(f"Model output field 'final_rationale' is empty for candidate {cid}")

    return {
        "candidate_id": cid,
        "total_score": total_score,
        "subscores": subscores,
        "recommendation": recommendation,
        "top_strengths": clean_object_list(model_result.get("top_strengths"), ["dimension", "reason", "resume_evidence"]),
        "main_gaps": clean_object_list(model_result.get("main_gaps"), ["dimension", "reason", "missing_or_weaker_evidence"]),
        "evidence_trace": clean_object_list(model_result.get("evidence_trace"), ["jd_requirement", "resume_evidence", "impact_on_score"]),
        "final_rationale": final_rationale,
    }


def call_api(*, experiment_name: str, raw_fallback_name: str, model: str, payload: Dict[str, Any], temperature: float) -> Dict[str, Any]:
    return call_structured_json(
        instructions=EXACT_PROMPT,
        payload=payload,
        schema_name=experiment_name,
        schema_description="Single candidate evaluation with exact required output schema",
        output_schema=OUTPUT_SCHEMA,
        raw_fallback_name=raw_fallback_name,
        model=model,
        temperature=temperature,
    )


def run_single_evaluation(*, experiment_name: str, raw_fallback_name: str) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("jd", help="Path to a single JD JSON file")
    parser.add_argument("cv", help="Path to a single CV JSON file")
    parser.add_argument("--out", default=f"{experiment_name}.json", help=f"Output file (default: {experiment_name}.json)")
    parser.add_argument("--model", default=get_default_model(), help=f"Model name (default from .env/environment: {get_default_model()})")
    parser.add_argument("--temperature", type=float, default=get_default_temperature(), help=f"Temperature (default from .env/environment: {get_default_temperature()})")
    args = parser.parse_args()

    jd_path = resolve_path_with_fallback(args.jd)
    cv_path = resolve_path_with_fallback(args.cv)
    out_path = resolve_path_with_fallback(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    jd_obj = load_single_jd(jd_path)
    cv_obj = load_single_cv(cv_path)
    assert_same_industry(jd_obj, jd_path, cv_obj, cv_path)
    payload = {"JD": jd_obj, "CV": cv_obj}
    model_json = call_api(
        experiment_name=experiment_name,
        raw_fallback_name=raw_fallback_name,
        model=args.model,
        payload=payload,
        temperature=args.temperature,
    )
    final_json = normalize_result(model_json, cv_obj)
    out_path.write_text(json.dumps(final_json, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(final_json, ensure_ascii=False, indent=2))
