from typing import Any, Dict, List


def _get_resources(data: Dict[str, Any], expected_type: str) -> List[Dict[str, Any]]:
    """
    Helper function to extract resources of a specific type from either a FHIR Bundle
    or a single FHIR resource dictionary.
    
    Args:
        data (Dict[str, Any]): The raw FHIR JSON data.
        expected_type (str): The expected FHIR resourceType (e.g., "Patient", "Condition").
        
    Returns:
        List[Dict[str, Any]]: A list of matching FHIR resource dictionaries.
    """
    if not isinstance(data, dict):
        return []

    resource_type = data.get("resourceType")
    
    if resource_type == "Bundle":
        return [
            entry.get("resource", {})
            for entry in data.get("entry", [])
            if isinstance(entry, dict) and entry.get("resource", {}).get("resourceType") == expected_type
        ]
    elif resource_type == expected_type:
        return [data]
        
    return []


def parse_patient(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract structured data from a FHIR Patient resource.
    
    Args:
        data (Dict[str, Any]): Raw FHIR JSON (Patient resource or Bundle).
        
    Returns:
        Dict[str, Any]: Structured patient data containing id, name, gender, birth_date, and identifiers.
    """
    resources = _get_resources(data, "Patient")
    if not resources:
        return {}
        
    resource = resources[0]
    
    name_list = resource.get("name", [])
    full_name = ""
    if name_list and isinstance(name_list, list):
        first_name = name_list[0]
        given = " ".join(first_name.get("given", []))
        family = first_name.get("family", "")
        full_name = f"{given} {family}".strip()

    identifiers = [
        {"system": i.get("system"), "value": i.get("value")}
        for i in resource.get("identifier", [])
        if isinstance(i, dict)
    ]

    return {
        "id": resource.get("id"),
        "name": full_name,
        "gender": resource.get("gender"),
        "birth_date": resource.get("birthDate"),
        "identifiers": identifiers
    }


def parse_condition(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract structured data from FHIR Condition resources.
    
    Args:
        data (Dict[str, Any]): Raw FHIR JSON (Condition resource or Bundle).
        
    Returns:
        List[Dict[str, Any]]: List of structured condition data.
    """
    resources = _get_resources(data, "Condition")
    parsed = []
    
    for resource in resources:
        code_concept = resource.get("code", {})
        codings = code_concept.get("coding", [])
        code = codings[0].get("code") if codings else None
        display = codings[0].get("display") if codings else code_concept.get("text")

        clinical_status_concept = resource.get("clinicalStatus", {})
        clinical_status_codings = clinical_status_concept.get("coding", [])
        clinical_status = clinical_status_codings[0].get("code") if clinical_status_codings else None

        parsed.append({
            "id": resource.get("id"),
            "clinical_status": clinical_status,
            "code": code,
            "display": display,
            "recorded_date": resource.get("recordedDate")
        })
        
    return parsed


def parse_medication_request(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract structured data from FHIR MedicationRequest resources.
    
    Args:
        data (Dict[str, Any]): Raw FHIR JSON (MedicationRequest resource or Bundle).
        
    Returns:
        List[Dict[str, Any]]: List of structured medication request data.
    """
    resources = _get_resources(data, "MedicationRequest")
    parsed = []
    
    for resource in resources:
        med_concept = resource.get("medicationCodeableConcept", {})
        codings = med_concept.get("coding", [])
        code = codings[0].get("code") if codings else None
        display = codings[0].get("display") if codings else med_concept.get("text")

        if not code and not display:
            med_ref = resource.get("medicationReference", {})
            display = med_ref.get("display")
            code = med_ref.get("reference")

        dosage_instructions = resource.get("dosageInstruction", [])
        dosage_text = dosage_instructions[0].get("text") if dosage_instructions else None

        parsed.append({
            "id": resource.get("id"),
            "status": resource.get("status"),
            "intent": resource.get("intent"),
            "medication_code": code,
            "medication_display": display,
            "dosage_text": dosage_text,
            "authored_on": resource.get("authoredOn")
        })
        
    return parsed


def parse_observation(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract structured data from FHIR Observation resources.
    
    Args:
        data (Dict[str, Any]): Raw FHIR JSON (Observation resource or Bundle).
        
    Returns:
        List[Dict[str, Any]]: List of structured observation data.
    """
    resources = _get_resources(data, "Observation")
    parsed = []
    
    for resource in resources:
        code_concept = resource.get("code", {})
        codings = code_concept.get("coding", [])
        code = codings[0].get("code") if codings else None
        display = codings[0].get("display") if codings else code_concept.get("text")

        value = None
        unit = None
        
        if "valueQuantity" in resource:
            vq = resource["valueQuantity"]
            value = vq.get("value")
            unit = vq.get("unit") or vq.get("code")
        elif "valueCodeableConcept" in resource:
            vcc = resource["valueCodeableConcept"]
            v_codings = vcc.get("coding", [])
            value = v_codings[0].get("display") if v_codings else vcc.get("text")
        elif "valueString" in resource:
            value = resource["valueString"]

        effective_date = resource.get("effectiveDateTime")
        if not effective_date:
            effective_date = resource.get("effectivePeriod", {}).get("start")

        parsed.append({
            "id": resource.get("id"),
            "status": resource.get("status"),
            "code": code,
            "display": display,
            "value": value,
            "unit": unit,
            "effective_date": effective_date
        })
        
    return parsed


def parse_coverage(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract structured data from FHIR Coverage resources.
    
    Args:
        data (Dict[str, Any]): Raw FHIR JSON (Coverage resource or Bundle).
        
    Returns:
        List[Dict[str, Any]]: List of structured coverage data.
    """
    resources = _get_resources(data, "Coverage")
    parsed = []
    
    for resource in resources:
        payors = resource.get("payor", [])
        payor_ref = payors[0].get("reference") if payors else None
        payor_display = payors[0].get("display") if payors else None

        classes = resource.get("class", [])
        plan_id = None
        plan_name = None
        for cls in classes:
            if not isinstance(cls, dict):
                continue
            cls_type = cls.get("type", {}).get("coding", [{}])[0].get("code")
            if cls_type == "plan":
                plan_id = cls.get("value")
                plan_name = cls.get("name")
                break

        parsed.append({
            "id": resource.get("id"),
            "status": resource.get("status"),
            "subscriber_id": resource.get("subscriberId"),
            "payor_reference": payor_ref,
            "payor_display": payor_display,
            "plan_id": plan_id,
            "plan_name": plan_name,
            "period_start": resource.get("period", {}).get("start"),
            "period_end": resource.get("period", {}).get("end")
        })
        
    return parsed