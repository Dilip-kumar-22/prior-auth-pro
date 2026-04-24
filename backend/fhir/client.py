import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class CircuitBreakerOpenException(Exception):
    """Exception raised when the circuit breaker is open and requests are blocked."""
    pass


class CircuitBreaker:
    """
    A lightweight stateful circuit breaker to prevent cascading failures
    when the external FHIR server is unresponsive.
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout_seconds: int = 60) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = timedelta(seconds=recovery_timeout_seconds)
        self.failures = 0
        self.state = "CLOSED"
        self.last_failure_time: Optional[datetime] = None

    def record_failure(self) -> None:
        """Record a failed request and potentially open the circuit."""
        self.failures += 1
        self.last_failure_time = datetime.utcnow()
        if self.failures >= self.failure_threshold:
            if self.state != "OPEN":
                logger.warning("FHIR Client Circuit Breaker changed state to OPEN")
            self.state = "OPEN"

    def record_success(self) -> None:
        """Record a successful request and close the circuit if it was open or half-open."""
        if self.state != "CLOSED":
            logger.info("FHIR Client Circuit Breaker changed state to CLOSED")
        self.failures = 0
        self.state = "CLOSED"
        self.last_failure_time = None

    def can_request(self) -> bool:
        """Check if a request is allowed to proceed based on the current state."""
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if self.last_failure_time and datetime.utcnow() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
                logger.info("FHIR Client Circuit Breaker changed state to HALF_OPEN")
                return True
            return False
        if self.state == "HALF_OPEN":
            return True
        return False


class FHIRClient:
    """
    Async FHIR R4 REST client using httpx.
    Implements circuit breakers and exponential backoff for resilience.
    """

    def __init__(self, base_url: str, token: Optional[str] = None, timeout: float = 30.0) -> None:
        """
        Initialize the FHIR client.

        Args:
            base_url (str): The base URL of the FHIR R4 server.
            token (Optional[str]): Optional Bearer token for authentication.
            timeout (float): Request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        headers = {"Accept": "application/fhir+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
            
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=timeout
        )
        self.circuit_breaker = CircuitBreaker()

    async def close(self) -> None:
        """Close the underlying httpx client."""
        await self.client.aclose()

    async def __aenter__(self) -> "FHIRClient":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Internal method to execute HTTP requests with retries and circuit breaking.

        Args:
            method (str): HTTP method (e.g., "GET").
            path (str): Endpoint path relative to base_url.
            params (Optional[Dict[str, Any]]): Query parameters.

        Returns:
            Dict[str, Any]: Parsed JSON response.

        Raises:
            CircuitBreakerOpenException: If the circuit breaker is open.
            httpx.HTTPError: If the request fails after all retries.
        """
        if not self.circuit_breaker.can_request():
            logger.error("FHIR request blocked: Circuit breaker is OPEN")
            raise CircuitBreakerOpenException("FHIR server is currently unreachable.")

        max_retries = 3
        base_delay = 1.0

        for attempt in range(max_retries):
            try:
                response = await self.client.request(method, path, params=params)
                response.raise_for_status()
                self.circuit_breaker.record_success()
                return response.json()
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                if status in (429, 500, 502, 503, 504):
                    self.circuit_breaker.record_failure()
                    if attempt == max_retries - 1:
                        logger.error(f"FHIR request failed after {max_retries} attempts: HTTP {status}")
                        raise
                else:
                    # Client errors (400, 401, 403, 404) should not trigger retries or circuit breaker
                    logger.warning(f"FHIR client error: HTTP {status} for path {path}")
                    raise
            except httpx.RequestError as e:
                self.circuit_breaker.record_failure()
                if attempt == max_retries - 1:
                    logger.error(f"FHIR request failed after {max_retries} attempts: {str(e)}")
                    raise

            # Exponential backoff
            delay = base_delay * (2 ** attempt)
            logger.debug(f"Retrying FHIR request in {delay} seconds (attempt {attempt + 1}/{max_retries})")
            await asyncio.sleep(delay)
            
        raise RuntimeError("Unexpected execution path in FHIR client _request")

    async def read(self, resource_type: str, resource_id: str) -> Dict[str, Any]:
        """
        Read a specific FHIR resource by ID.

        Args:
            resource_type (str): The type of FHIR resource (e.g., "Patient").
            resource_id (str): The logical ID of the resource.

        Returns:
            Dict[str, Any]: The FHIR resource as a dictionary.
        """
        path = f"/{resource_type}/{resource_id}"
        return await self._request("GET", path)

    async def search(self, resource_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Search for FHIR resources matching the given parameters.

        Args:
            resource_type (str): The type of FHIR resource (e.g., "Condition").
            params (Dict[str, Any]): Search parameters.

        Returns:
            Dict[str, Any]: A FHIR Bundle containing the search results.
        """
        path = f"/{resource_type}"
        return await self._request("GET", path, params=params)

    async def get_patient(self, patient_id: str) -> Dict[str, Any]:
        """
        Retrieve a Patient resource by ID.

        Args:
            patient_id (str): The logical ID of the patient.

        Returns:
            Dict[str, Any]: The Patient resource.
        """
        return await self.read("Patient", patient_id)

    async def get_conditions(self, patient_id: str) -> Dict[str, Any]:
        """
        Retrieve all Condition resources for a specific patient.

        Args:
            patient_id (str): The logical ID of the patient.

        Returns:
            Dict[str, Any]: A FHIR Bundle of Condition resources.
        """
        return await self.search("Condition", {"patient": patient_id})

    async def get_medications(self, patient_id: str) -> Dict[str, Any]:
        """
        Retrieve all MedicationRequest resources for a specific patient.

        Args:
            patient_id (str): The logical ID of the patient.

        Returns:
            Dict[str, Any]: A FHIR Bundle of MedicationRequest resources.
        """
        return await self.search("MedicationRequest", {"patient": patient_id})

    async def get_observations(self, patient_id: str) -> Dict[str, Any]:
        """
        Retrieve all Observation resources for a specific patient.

        Args:
            patient_id (str): The logical ID of the patient.

        Returns:
            Dict[str, Any]: A FHIR Bundle of Observation resources.
        """
        return await self.search("Observation", {"patient": patient_id})

    async def get_procedures(self, patient_id: str) -> Dict[str, Any]:
        """
        Retrieve all Procedure resources for a specific patient.

        Args:
            patient_id (str): The logical ID of the patient.

        Returns:
            Dict[str, Any]: A FHIR Bundle of Procedure resources.
        """
        return await self.search("Procedure", {"patient": patient_id})

    async def get_coverage(self, patient_id: str) -> Dict[str, Any]:
        """
        Retrieve all Coverage resources for a specific patient.

        Args:
            patient_id (str): The logical ID of the patient.

        Returns:
            Dict[str, Any]: A FHIR Bundle of Coverage resources.
        """
        return await self.search("Coverage", {"patient": patient_id, "status": "active"})

    async def get_all_for_auth(self, patient_id: str) -> Dict[str, Any]:
        """
        Concurrently gather all relevant FHIR resources for a patient to support
        a Prior Authorization request.

        Args:
            patient_id (str): The logical ID of the patient.

        Returns:
            Dict[str, Any]: A consolidated dictionary containing the Patient, Conditions,
                            MedicationRequests, Observations, Procedures, and Coverages.
        """
        results = await asyncio.gather(
            self.get_patient(patient_id),
            self.get_conditions(patient_id),
            self.get_medications(patient_id),
            self.get_observations(patient_id),
            self.get_procedures(patient_id),
            self.get_coverage(patient_id),
            return_exceptions=True
        )

        def _extract_result(result: Any) -> Any:
            if isinstance(result, Exception):
                logger.warning(f"Failed to fetch FHIR resource during get_all_for_auth: {str(result)}")
                return {"error": str(result)}
            return result

        return {
            "Patient": _extract_result(results[0]),
            "Condition": _extract_result(results[1]),
            "MedicationRequest": _extract_result(results[2]),
            "Observation": _extract_result(results[3]),
            "Procedure": _extract_result(results[4]),
            "Coverage": _extract_result(results[5])
        }