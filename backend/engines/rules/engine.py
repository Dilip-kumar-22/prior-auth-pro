import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class RulesEngine:
    """
    Deterministic rules engine for evaluating Prior Authorization requests against payer policies.
    
    Loads synthetic payer policies from JSON seed files and evaluates incoming requests
    to determine if they meet criteria for auto-approval, auto-denial, or if they require
    further AI-driven clinical reasoning and review.
    """

    def __init__(self, seed_dir: str = "engines/rules/seed_data") -> None:
        """
        Initialize the RulesEngine and load policies from the specified directory.
        
        Args:
            seed_dir (str): Path to the directory containing JSON seed files for payer policies.
        """
        # Resolve path relative to the project root if necessary
        base_path = Path(__file__).resolve().parent.parent.parent
        target_dir = base_path / seed_dir if not Path(seed_dir).is_absolute() else Path(seed_dir)
        
        self.seed_dir: Path = target_dir
        self.policies: List[Dict[str, Any]] = []
        self.load_policies()

    def load_policies(self) -> List[Dict[str, Any]]:
        """
        Load payer policies from JSON seed files in the configured seed directory.
        
        Returns:
            List[Dict[str, Any]]: A list of loaded payer policy dictionaries.
        """
        self.policies = []
        
        if not self.seed_dir.exists() or not self.seed_dir.is_dir():
            logger.warning(f"Seed directory {self.seed_dir} does not exist or is not a directory.")
            return self.policies

        for file_path in self.seed_dir.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.policies.extend(data)
                    elif isinstance(data, dict):
                        self.policies.append(data)
            except Exception as e:
                logger.error(f"Failed to load policy file {file_path}", extra={"error": str(e)})
        
        logger.info(f"Loaded {len(self.policies)} payer policies from {self.seed_dir}.")
        return self.policies

    def evaluate(self, request: Any) -> Dict[str, Any]:
        """
        Evaluate an authorization request against loaded payer policies.
        
        Checks auto_deny criteria first, then auto_approve criteria, and finally
        flags for AI review if neither deterministic condition is met or if the policy
        explicitly requires it.
        
        Args:
            request (Any): The authorization request to evaluate. Can be a dictionary,
                           a Pydantic model, or an SQLAlchemy ORM model.
                           
        Returns:
            Dict[str, Any]: A dictionary containing the evaluation decision:
                - decision (str): 'approve', 'deny', or 'review'
                - matched_policy (Optional[str]): The policy_code of the matched policy
                - reason (str): Explanation for the decision
                - requires_ai (bool): True if the request needs AI clinical reasoning
        """
        # Extract request details robustly (handles dicts and objects)
        if isinstance(request, dict):
            payer_id = str(request.get("payer_id", "")).lower()
            service_requested = str(request.get("service_requested", ""))
            diagnosis_codes = request.get("diagnosis_codes", [])
        else:
            payer_id = str(getattr(request, "payer_id", "")).lower()
            service_requested = str(getattr(request, "service_requested", ""))
            diagnosis_codes = getattr(request, "diagnosis_codes", [])

        # Normalize diagnosis codes into a simple list of strings
        req_dx_codes: List[str] = []
        if diagnosis_codes:
            for dx in diagnosis_codes:
                if isinstance(dx, dict) and "code" in dx:
                    req_dx_codes.append(str(dx["code"]))
                elif isinstance(dx, str):
                    req_dx_codes.append(dx)

        # 1. Find matching policy
        matched_policy: Optional[Dict[str, Any]] = None
        
        # Attempt to match by payer_name and service_requested
        for policy in self.policies:
            p_name = str(policy.get("payer_name", "")).lower()
            if p_name in payer_id or payer_id in p_name:
                if service_requested in policy.get("cpt_codes", []):
                    matched_policy = policy
                    break
        
        # Fallback: match strictly by service_requested if payer matching fails
        if not matched_policy:
            for policy in self.policies:
                if service_requested in policy.get("cpt_codes", []):
                    matched_policy = policy
                    break

        if not matched_policy:
            return {
                "decision": "review",
                "matched_policy": None,
                "reason": f"No matching policy found for service '{service_requested}'.",
                "requires_ai": True
            }

        policy_code = matched_policy.get("policy_code")

        # 2. Check auto-deny criteria
        auto_deny = matched_policy.get("auto_deny_criteria", {})
        excluded_services = auto_deny.get("excluded_service_codes", [])
        
        if service_requested in excluded_services:
            return {
                "decision": "deny",
                "matched_policy": policy_code,
                "reason": f"Service {service_requested} is explicitly excluded by policy.",
                "requires_ai": False
            }

        # 3. Check auto-approve criteria
        auto_approve = matched_policy.get("auto_approve_criteria", {})
        qualifying_dx = auto_approve.get("qualifying_diagnoses", [])
        icd10_req = matched_policy.get("icd10_required", [])
        
        # Combine qualifying and required diagnoses for intersection check
        approved_dx = set(qualifying_dx) | set(icd10_req)
        
        if approved_dx and any(dx in approved_dx for dx in req_dx_codes):
            return {
                "decision": "approve",
                "matched_policy": policy_code,
                "reason": "Request meets auto-approval criteria for diagnosis and service.",
                "requires_ai": False
            }

        # 4. Check AI review flag
        if matched_policy.get("requires_ai_review", False):
            return {
                "decision": "review",
                "matched_policy": policy_code,
                "reason": "Policy explicitly requires AI clinical review.",
                "requires_ai": True
            }

        # 5. Default to review if no criteria matched
        return {
            "decision": "review",
            "matched_policy": policy_code,
            "reason": "Request does not meet strict auto-approve or auto-deny criteria. Requires clinical review.",
            "requires_ai": True
        }