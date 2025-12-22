from __future__ import annotations
from enum import Enum
from typing import List, Optional, Any, Dict, Literal, Union
from pydantic import BaseModel, Field
from functools import cached_property



class Result(str, Enum):
    """
    Enumeration of possible outcomes for a compliance test.
    """
    PASS = "PASS"
    FAIL = "FAIL"
    CONCERN = "CONCERN"
    NA = "NA"


class TestResult(BaseModel):
    """
    Represents the outcome of a single compliance test.

    Attributes:
        test_number (int): Numeric identifier of the test (must be ≥ 1).
        name (str): Human-readable name of the test.
        result (Result): Final status (PASS, FAIL, CONCERN, NA).
        message (str): Descriptive message explaining the outcome.
    """
    test_number: int = Field(..., ge=1)
    name: str
    result: Result
    message: str


class ATOStatus(BaseModel):
    """
    Aggregates results across all executed tests and provides summary counts.
    """
    system_name: Optional[str] = None
    pass_count: int = 0
    fail_count: int = 0
    concern_count: int = 0
    na_count: int = 0
    results: List[TestResult] = Field(default_factory=list)

    def add(self, test_result: TestResult) -> None:
        """
        Add a new TestResult to the collection and update counters.

        Args:
            test_result (TestResult): The result object from an executed test.
        """
        self.results.append(test_result)

        if test_result.result == Result.PASS:
            self.pass_count += 1
        elif test_result.result == Result.FAIL:
            self.fail_count += 1
        elif test_result.result == Result.CONCERN:
            self.concern_count += 1
        elif test_result.result == Result.NA:
            self.na_count += 1

    def summary(self) -> str:
        """
        Produce a one-line summary of all test outcomes.

        Returns:
            str: Aggregated counts in human-readable format.
        """
        total = len(self.results)
        return (
            f"Total: {total} | "
            f"PASS: {self.pass_count} | "
            f"FAIL: {self.fail_count} | "
            f"CONCERN: {self.concern_count} | "
            f"N/A: {self.na_count}"
        )





CIA = Literal["Low", "Moderate", "Medium", "High"]  # include both “Moderate|Medium” if we see both

class RawPayloads(BaseModel):
    system_info: Optional[Dict[str, Any]] = Field(None, description="GET /systems/{id}")
    workflow_pac: Optional[Dict[str, Any]] = None
    hardware_summary: Optional[List[Dict[str, Any]]] = None
    software_summary: Optional[List[Dict[str, Any]]] = None
    artifact_summary: Optional[List[Dict[str, Any]]] = None
    artifact_details: Optional[List[Dict[str, Any]]] = None
    workflows_instances: Optional[List[Dict[str, Any]]] = None
    system_status_details: Optional[List[Dict[str, Any]]] = None
    privacy_summary: Optional[List[Dict[str, Any]]] = None
    test_results: Optional[List[Dict[str, Any]]] = None
    controls: Optional[List[Dict[str, Any]]] = None  # <── add this
    cac_pac: Optional[Dict[str, Any]] = None
    user_assignments_details: Optional[List[Dict[str, Any]]] = None
    device_findings_details: Optional[List[Dict[str, Any]]] = None
    system_poam_details: Optional[List[Dict[str, Any]]] = None
    software_details: Optional[List[Dict[str, Any]]] = None
    hardware_details: Optional[List[Dict[str, Any]]] = None
    associations_details: Optional[List[Dict[str, Any]]] = None
    connectivity_ccsd_details: Optional[List[Dict[str, Any]]] = None





# -------------------------
# Artifact / Evidence stuff
# -------------------------

class ArtifactDetails(BaseModel):
    ap_associations: Optional[str] = None
    artifact_name: Optional[str] = None
    authorization_status: Optional[str] = None
    authorization_termination_date: Optional[str] = None
    category: Optional[str] = None
    control_associations: Optional[str] = None
    created_by: Optional[str] = None
    created_date: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None
    description: Optional[str] = None
    download_url: Optional[str] = None
    expiration_date: Optional[str] = None
    filename: Optional[str] = None
    inherited_from: Optional[str] = None
    last_modified: Optional[str] = None
    last_reviewed: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    organization: Optional[str] = None
    organization_hierarchy: Optional[str] = None
    pagination: Optional[Dict[str, Any]] = None
    policy: Optional[str] = None
    reference: Optional[str] = None
    registration_type: Optional[str] = None
    remote_inheritance_instance: Optional[str] = None
    signed_date: Optional[str] = None
    system_acronym: Optional[str] = None
    system_id: Optional[str] = None
    system_name: Optional[str] = None
    template: Optional[str] = None
    type: Optional[str] = None


class ArtifactSummary(BaseModel):
    artifacts_w_o_control_ap_associations: Optional[str] = None
    authorization_status: Optional[str] = None
    authorization_termination_date: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None
    expired_artifacts: Optional[str] = None
    expiring_artifacts: Optional[str] = None
    inherited_artifacts: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    organization: Optional[str] = None
    organization_hierarchy: Optional[str] = None
    pagination: Optional[Dict[str, Any]] = None
    policy: Optional[str] = None
    registration_type: Optional[str] = None
    system_acronym: Optional[str] = None
    system_id: Optional[str] = None
    system_name: Optional[str] = None
    total_artifacts: Optional[str] = None


# -------------------------
# System relationships / inheritance
# -------------------------

class Associations(BaseModel):
    aps_provided: Optional[str] = None
    aps_received: Optional[str] = None
    associated_system_acronym: Optional[str] = None
    associated_system_id: Optional[str] = None
    associated_system_name: Optional[str] = None
    authorization_status: Optional[str] = None
    authorization_termination_date: Optional[str] = None
    controls_provided: Optional[str] = None
    controls_received: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None
    date_established: Optional[str] = None
    external_system: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    organization: Optional[str] = None
    owning_organization: Optional[str] = None
    pagination: Optional[Dict[str, Any]] = None
    relationship_description: Optional[str] = None
    relationship_type: Optional[str] = None
    remote_inheritance_instance: Optional[str] = None
    system_acronym: Optional[str] = None
    system_id: Optional[str] = None
    system_name: Optional[str] = None
    system_type: Optional[str] = None


# -------------------------
# RMF / workflow
# -------------------------

class CAC(BaseModel):
    compliancestatus: Optional[str] = None
    controlacronym: Optional[str] = None
    currentstage: Optional[int] = None
    currentstagename: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None
    meta: Optional[Dict[str, Any]] = None
    systemid: Optional[int] = None
    totalstages: Optional[int] = None


class WorkflowDashboard(BaseModel):
    createddate: Optional[float] = None
    currentstage: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None
    lasteditedby: Optional[str] = None
    lastediteddate: Optional[float] = None
    meta: Optional[Dict[str, Any]] = None
    packagename: Optional[str] = None
    pagination: Optional[Dict[str, Any]] = None
    systemid: Optional[int] = None
    systemname: Optional[str] = None
    transitions: Optional[str] = None
    version: Optional[int] = None
    workflow: Optional[str] = None
    workflowinstanceid: Optional[int] = None
    workflowuid: Optional[str] = None


class Workflows(BaseModel):
    data: Optional[Any] = None
    meta: Optional[Dict[str, Any]] = None


# -------------------------
# Controls / security posture
# -------------------------

class Controls(BaseModel):
    acronym: Optional[str] = None
    ccis: Optional[str] = None
    compliancestatus: Optional[str] = None
    controldesignation: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None
    estimatedcompletiondate: Optional[float] = None
    impact: Optional[Any] = None
    impactdescription: Optional[Any] = None
    implementationnarrative: Optional[str] = None
    implementationstatus: Optional[str] = None
    includedstatus: Optional[str] = None
    isinherited: Optional[bool] = None
    likelihood: Optional[Any] = None
    meta: Optional[Dict[str, Any]] = None
    mitigations: Optional[Any] = None
    modifiedbyoverlays: Optional[str] = None
    name: Optional[str] = None
    recommendations: Optional[Any] = None
    relevanceofthreat: Optional[Any] = None
    residualrisklevel: Optional[Any] = None
    responsibleentities: Optional[str] = None
    severity: Optional[Any] = None
    slcmcomments: Optional[str] = None
    slcmcriticality: Optional[str] = None
    slcmfrequency: Optional[str] = None
    slcmmethod: Optional[str] = None
    slcmreporting: Optional[str] = None
    slcmtracking: Optional[str] = None
    systemid: Optional[int] = None
    testmethod: Optional[Any] = None
    vulnerabilitysummary: Optional[Any] = None


class TestResults(BaseModel):
    assessmentprocedure: Optional[str] = None
    cci: Optional[str] = None
    compliancestatus: Optional[str] = None
    control: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None
    description: Optional[str] = None
    isinherited: Optional[bool] = None
    meta: Optional[Dict[str, Any]] = None
    pagination: Optional[Dict[str, Any]] = None
    systemid: Optional[int] = None
    testdate: Optional[float] = None
    testedby: Optional[str] = None
    type: Optional[str] = None


# -------------------------
# Vulnerabilities / Findings
# -------------------------

class Findings(BaseModel):
    benchmark: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None
    first_seen_date: Optional[str] = None
    hostname: Optional[str] = None
    ingested_date: Optional[str] = None
    last_scan_date: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    nickname: Optional[str] = None
    organization: Optional[str] = None
    organization_hierarchy: Optional[str] = None
    pagination: Optional[Dict[str, Any]] = None
    raw_severity: Optional[str] = None
    result: Optional[str] = None
    scan_type: Optional[str] = None
    security_check: Optional[str] = None
    system_acronym: Optional[str] = None
    system_id: Optional[str] = None
    system_name: Optional[str] = None
    version_release: Optional[str] = None


# -------------------------
# Hardware / Software inventory
# -------------------------

class Hardware(BaseModel):
    authorization_status: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None
    hardware_matching_criteria: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    organization: Optional[str] = None
    organization_hierarchy: Optional[str] = None
    pagination: Optional[Dict[str, Any]] = None
    policy: Optional[str] = None
    registration_completion_date: Optional[str] = None
    system_acronym: Optional[str] = None
    system_id: Optional[str] = None
    system_name: Optional[str] = None
    total_hardware_assets: Optional[str] = None


class HardwareDetailsDashboard(BaseModel):
    data: Optional[List[Dict[str, Any]]] = None
    domain: Optional[str] = None
    fqdn: Optional[str] = None
    host_name: Optional[str] = None
    ip_address: Optional[str] = None
    last_scan_date: Optional[str] = None
    mac_address: Optional[str] = None
    manufacturer: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    model: Optional[str] = None
    nickname: Optional[str] = None
    operating_system_os: Optional[str] = None
    organization: Optional[str] = None
    organization_hierarchy: Optional[str] = None
    pagination: Optional[Dict[str, Any]] = None
    record_identifier: Optional[str] = None
    resource: Optional[str] = None
    serial_number: Optional[str] = None
    system_acronym: Optional[str] = None
    system_id: Optional[str] = None
    system_name: Optional[str] = None


class Software(BaseModel):
    authorization_status: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None
    licenses_used: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    organization: Optional[str] = None
    organization_hierarchy: Optional[str] = None
    pagination: Optional[Dict[str, Any]] = None
    policy: Optional[str] = None
    registration_completion_date: Optional[int] = None
    software_matching_criteria: Optional[str] = None
    system_acronym: Optional[str] = None
    system_id: Optional[str] = None
    system_name: Optional[str] = None
    total_licenses: Optional[str] = None
    total_software_assets: Optional[str] = None


class SoftwareDetailsDashboard(BaseModel):
    approval_date: Optional[str] = None
    approval_status: Optional[str] = None
    cost_per_license: Optional[str] = None
    critical_asset: Optional[str] = None
    cryptographic_hash: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None
    date_reviewed_updated: Optional[str] = None
    end_of_life_support_date: Optional[str] = None
    extended_end_of_life_support_date: Optional[str] = None
    fiscal_year_fy: Optional[str] = None
    hosting_environment: Optional[str] = None
    in_service_data: Optional[str] = None
    it_budget_uii: Optional[str] = None
    license_expiration_date: Optional[str] = None
    license_or_contract: Optional[str] = None
    license_poc: Optional[str] = None
    license_renewal_date: Optional[str] = None
    license_term: Optional[str] = None
    licenses_used: Optional[str] = None
    location: Optional[str] = None
    maintenance_date: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    network: Optional[str] = None
    organization: Optional[str] = None
    pagination: Optional[Dict[str, Any]] = None
    parent_system: Optional[str] = None
    poc_email: Optional[str] = None
    poc_first_name: Optional[str] = None
    poc_last_name: Optional[str] = None
    poc_office_organization: Optional[str] = None
    poc_phone_number: Optional[str] = None
    pop_end_date: Optional[str] = None
    purpose: Optional[str] = None
    release_date: Optional[str] = None
    retirement_date: Optional[str] = None
    reviewed_updated_by: Optional[str] = None
    software_dependencies: Optional[str] = None
    software_name: Optional[str] = None
    software_type: Optional[str] = None
    software_vendor: Optional[str] = None
    software_version: Optional[str] = None
    subsystem: Optional[str] = None
    system_acronym: Optional[str] = None
    system_id: Optional[str] = None
    system_name: Optional[str] = None
    system_type: Optional[str] = None
    total_license_cost: Optional[str] = None
    total_licenses: Optional[str] = None


# -------------------------
# Privacy / classification / PHI / PII
# -------------------------

class Privacy(BaseModel):
    atos_in_current_fy: Optional[str] = None
    authorization_status: Optional[str] = None
    controlled_unclassified_information_cui: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None
    hipaa_coverage: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    organization: Optional[str] = None
    organization_hierarchy: Optional[str] = None
    pagination: Optional[Dict[str, Any]] = None
    personally_identifiable_information_pii: Optional[str] = None
    pia_date: Optional[int] = None
    pia_required: Optional[str] = None
    pia_status: Optional[str] = None
    policy: Optional[str] = None
    privacy_overlay_applied: Optional[str] = None
    privacy_overlays_responses: Optional[str] = None
    protected_health_information_phi: Optional[str] = None
    registration_completion_date: Optional[int] = None
    registration_type: Optional[str] = None
    system_acronym: Optional[str] = None
    system_id: Optional[str] = None
    system_life_cycle_acquisition_phase: Optional[str] = None
    system_name: Optional[str] = None
    system_of_records_notice_required: Optional[str] = None
    system_type: Optional[str] = None


# -------------------------
# System-level rollup / dashboards
# -------------------------

class SystemDetailsDashboard(BaseModel):
    applied_overlays: Optional[str] = None
    atc_decision: Optional[str] = None
    atc_decision_date: Optional[int] = None
    atc_termination_date: Optional[str] = None
    atd: Optional[int] = None
    authorization_date: Optional[int] = None
    authorization_status: Optional[str] = None
    availability: Optional[str] = None
    baseline_location: Optional[str] = None
    city_primary_location: Optional[str] = None
    cloud_computing: Optional[str] = None
    confidentiality: Optional[str] = None
    controlled_unclassified_information_cui: Optional[str] = None
    current_ao: Optional[str] = None
    cybersecurity_service_provider: Optional[str] = None
    cybersecurity_service_provider_exception_justification: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None
    data_id: Optional[str] = None
    days_to_annual_review: Optional[str] = None
    days_to_atd: Optional[str] = None
    days_to_reported_atd: Optional[str] = None
    deployment_locations: Optional[str] = None
    dod_confidentiality: Optional[str] = None
    financial_management_system: Optional[str] = None
    governing_mission_area: Optional[str] = None
    highest_system_data_classification: Optional[str] = None
    impact: Optional[str] = None
    installation_name_primary_location: Optional[str] = None
    integrity: Optional[str] = None
    iso_pm: Optional[str] = None
    lifecycle_acquisition_phase: Optional[str] = None
    location_in_pac: Optional[str] = None
    mac: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    mission_criticality: Optional[str] = None
    mission_portfolio: Optional[str] = None
    national_security_system: Optional[str] = None
    need_date: Optional[str] = None
    nss_questionnaire_completed: Optional[str] = None
    organization_hierarchy: Optional[str] = None
    organization_name: Optional[str] = None
    overall_risk_score: Optional[str] = None
    package_created: Optional[int] = None
    package_days_at_role: Optional[str] = None
    package_name: Optional[str] = None
    package_type: Optional[str] = None
    pagination: Optional[Dict[str, Any]] = None
    personally_identifiable_information_pii: Optional[str] = None
    protected_health_information_phi: Optional[str] = None
    public_facing_component_presence: Optional[str] = None
    reciprocity_system: Optional[str] = None
    registration_completion_date: Optional[int] = None
    registration_type: Optional[str] = None
    reported_atd: Optional[int] = None
    reported_authorization_date: Optional[int] = None
    reported_authorization_status: Optional[str] = None
    reported_policy: Optional[str] = None
    rmf_activity: Optional[str] = None
    security_controls_assessor_executive_summary: Optional[str] = None
    special_type: Optional[str] = None
    special_type_description: Optional[str] = None
    state_primary_location: Optional[str] = None
    street_address_primary_location: Optional[str] = None
    system_acronym: Optional[str] = None
    system_id: Optional[str] = None
    system_name: Optional[str] = None
    system_policy: Optional[str] = None
    system_type: Optional[str] = None
    terms_conditions_for_authorization_summary: Optional[str] = None
    terms_conditions_for_connection_summary: Optional[str] = None
    type_authorization: Optional[str] = None
    version_release_number: Optional[str] = None
    whitelist_id: Optional[str] = None
    zip_code_primary_location: Optional[str] = None


class SystemInfo(BaseModel):
    acquisitioncategory: Optional[str] = None
    acronym: Optional[str] = None
    appliedoverlays: Optional[str] = None
    appliedstigs: Optional[str] = None
    atciatcexpirationdate: Optional[int] = None
    atciatcgranteddate: Optional[int] = None
    atciatcpendingitems: Optional[str] = None
    authorizationdate: Optional[int] = None
    authorizationlength: Optional[int] = None
    authorizationstatus: Optional[str] = None
    authorizationtoconnectstatus: Optional[str] = None
    authterminationdate: Optional[int] = None
    availability: Optional[str] = None
    businessimpactanalysisartifact: Optional[str] = None
    businessimpactanalysisrequired: Optional[bool] = None
    cloudcomputing: Optional[bool] = None
    cloudtype: Optional[Any] = None
    confidentiality: Optional[str] = None
    connectivityauthorizationdate: Optional[int] = None
    connectivityauthorizationterminationdate: Optional[int] = None
    connectivityccsd: Optional[List[Any]] = None
    contingencyplanartifact: Optional[str] = None
    contingencyplanrequired: Optional[bool] = None
    contingencyplantestdate: Optional[Union[float, int]] = None
    contingencyplantested: Optional[bool] = None
    crossdomainticket: Optional[Any] = None
    currentrmflifecyclestep: Optional[str] = None
    cybersecurityserviceprovider: Optional[str] = None
    cybersecurityserviceproviderexceptionjustification: Optional[Any] = None
    data: Optional[List[Dict[str, Any]]] = None
    dataid: Optional[str] = None
    description: Optional[str] = None
    disasterrecoveryplanartifact: Optional[str] = None
    disasterrecoveryplanrequired: Optional[bool] = None
    eauthenticationriskassessmentartifact: Optional[str] = None
    eauthenticationriskassessmentdate: Optional[int] = None
    eauthenticationriskassessmentrequired: Optional[bool] = None
    governingmissionarea: Optional[str] = None
    hascui: Optional[bool] = None
    hasphi: Optional[bool] = None
    haspii: Optional[bool] = None
    highestsystemdataclassification: Optional[str] = None
    impact: Optional[str] = None
    incidentresponseplanartifact: Optional[str] = None
    incidentresponseplanrequired: Optional[bool] = None
    instance: Optional[str] = None
    integrity: Optional[str] = None
    interconnectedinformationsystemsandidentifiers: Optional[str] = None
    ipv4ipv6dualstackassets: Optional[int] = None
    ipv4onlyassets: Optional[int] = None
    ipv6onlyassets: Optional[int] = None
    isfinancialmanagement: Optional[bool] = None
    ishrr: Optional[Any] = None
    isiaas: Optional[bool] = None
    isnss: Optional[bool] = None
    ispaas: Optional[bool] = None
    ispublicfacing: Optional[bool] = None
    isreciprocity: Optional[bool] = None
    issaas: Optional[bool] = None
    istypeauthorization: Optional[bool] = None
    maximumtolerabledowntime: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    missioncriticality: Optional[str] = None
    missionportfolio: Optional[str] = None
    name: Optional[str] = None
    needdate: Optional[Any] = None
    nextsecurityreviewduedate: Optional[int] = None
    otherinformation: Optional[Any] = None
    otherservicemodels: Optional[Any] = None
    overallriskscore: Optional[str] = None
    owningorganization: Optional[str] = None
    package: Optional[Any] = None
    pendingitemsduedate: Optional[Any] = None
    policy: Optional[str] = None
    ppsmregistrationexemptionjustification: Optional[Any] = None
    ppsmregistrationrequired: Optional[bool] = None
    ppsmregistrynumber: Optional[str] = None
    primarycontrolset: Optional[str] = None
    primaryfunctionalarea: Optional[str] = None
    privacyactsystemofrecordsnoticerequired: Optional[bool] = None
    privacyimpactassessmentartifact: Optional[str] = None
    privacyimpactassessmentdate: Optional[Union[float, int]] = None
    privacyimpactassessmentrequired: Optional[bool] = None
    privacyimpactassessmentstatus: Optional[str] = None
    privacythresholdanalysisartifact: Optional[str] = None
    privacythresholdanalysiscompleted: Optional[bool] = None
    privacythresholdanalysisdate: Optional[int] = None
    reciprocityexemption: Optional[str] = None
    recoverypointobjective: Optional[str] = None
    recoverytimeobjective: Optional[str] = None
    registrationcompletiondate: Optional[float] = None
    registrationtype: Optional[str] = None
    reportsforscorecard: Optional[bool] = None
    rmfactivity: Optional[str] = None
    secondaryfunctionalarea: Optional[str] = None
    secondaryorganization: Optional[Any] = None
    securitycontrolsassessorexecutivesummary: Optional[str] = None
    securityplanapprovaldate: Optional[int] = None
    securityplanapprovalstatus: Optional[str] = None
    securityreviewcompleted: Optional[bool] = None
    securityreviewcompletiondate: Optional[int] = None
    securityreviewrequired: Optional[bool] = None
    softwarecategory: Optional[str] = None
    specialtype: Optional[Any] = None
    specialtypedescription: Optional[Any] = None
    systemid: Optional[int] = None
    systemlifecycleacquisitionphase: Optional[str] = None
    systemownershipcontrolled: Optional[str] = None
    systemtype: Optional[str] = None
    termsforauth: Optional[str] = None
    totalipassets: Optional[int] = None
    userdefinedfield1: Optional[Any] = None
    userdefinedfield2: Optional[Any] = None
    userdefinedfield3: Optional[Any] = None
    userdefinedfield4: Optional[Any] = None
    userdefinedfield5: Optional[Any] = None
    versionreleaseno: Optional[str] = None
    whitelistid: Optional[str] = None
    whitelistinventory: Optional[str] = None


class SystemPOAMDashboard(BaseModel):
    artifact_attachments: Optional[str] = None
    comments: Optional[str] = None
    completion_date: Optional[str] = None
    condition_id: Optional[str] = None
    control_criticality: Optional[str] = None
    control_implementation_status: Optional[str] = None
    control_title: Optional[str] = None
    controls_aps: Optional[str] = None
    created_date: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None
    extension_date: Optional[str] = None
    id: Optional[str] = None
    identified_in_cfo_audit_or_other_review: Optional[str] = None
    impact: Optional[str] = None
    impact_description: Optional[str] = None
    last_modified_date: Optional[str] = None
    latest_milestone_description: Optional[str] = None
    likelihood: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    milestone_created_date: Optional[str] = None
    milestone_review_status: Optional[str] = None
    milestone_scheduled_completion_date: Optional[str] = None
    mitigations: Optional[str] = None
    modified_by: Optional[str] = None
    non_personnel_cost_code: Optional[str] = None
    non_personnel_funded_amount: Optional[str] = None
    non_personnel_non_funded_obstacle_other_reason: Optional[str] = None
    non_personnel_non_funding_obstacle: Optional[str] = None
    non_personnel_unfunded_amount: Optional[str] = None
    organization: Optional[str] = None
    pagination: Optional[Dict[str, Any]] = None
    pending_extension_date: Optional[str] = None
    personnel_cost_code: Optional[str] = None
    personnel_funded_base_hours: Optional[str] = None
    personnel_non_funded_obstacle_other_reason: Optional[str] = None
    personnel_non_funding_obstacle: Optional[str] = None
    personnel_unfunded_base_hours: Optional[str] = None
    poam_item_review_status: Optional[str] = None
    poam_item_status: Optional[str] = None
    poam_url: Optional[str] = None
    poc: Optional[str] = None
    policy: Optional[str] = None
    raw_severity: Optional[str] = None
    recommendations: Optional[str] = None
    recommended_likelihood: Optional[str] = None
    recommended_residual_risk: Optional[str] = None
    relevance_of_threat: Optional[str] = None
    remote_inheritance_instance: Optional[str] = None
    residual_risk: Optional[str] = None
    resources: Optional[str] = None
    scheduled_completion_date: Optional[str] = None
    security_checks: Optional[str] = None
    severity: Optional[str] = None
    source: Optional[str] = None
    source_identifying_vulnerability: Optional[str] = None
    system_acronym: Optional[str] = None
    system_id: Optional[str] = None
    system_name: Optional[str] = None
    system_type: Optional[str] = None
    vulnerability_description: Optional[str] = None


# -------------------------
# Users / contacts
# -------------------------

class UserDetails(BaseModel):
    data: Optional[List[Dict[str, Any]]] = None
    email: Optional[str] = None
    first_name: Optional[str] = None
    home_organization: Optional[str] = None
    last_name: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    organization: Optional[str] = None
    organization_hierarchy: Optional[str] = None
    pagination: Optional[Dict[str, Any]] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    system_acronym: Optional[str] = None
    system_id: Optional[str] = None
    system_name: Optional[str] = None
    system_policy: Optional[str] = None
    user_id: Optional[str] = None


# -------------------------
# Misc / bootstrap
# -------------------------

class InitialTest(BaseModel):
    data: Optional[Dict[str, Any]] = None
    meta: Optional[Dict[str, Any]] = None
    success: Optional[bool] = None


# -------------------------
# Top-level container to hang off SystemContext
# -------------------------

class FixturesData(BaseModel):
    """
    High-level structured view of your static fixture blobs.
    This is the thing you'll hang off SystemContext, e.g.:

        class SystemContext(BaseModel):
            ...
            fixtures: FixturesData
    """

    # Artifacts / evidence
    artifact_details: Optional[ArtifactDetails] = None
    artifact_summary: Optional[ArtifactSummary] = None

    # Inventory / components
    hardware: Optional[Hardware] = None
    hardware_details: Optional[HardwareDetailsDashboard] = None
    software: Optional[Software] = None
    software_details: Optional[SoftwareDetailsDashboard] = None

    # Privacy / classification
    privacy: Optional[Privacy] = None

    # Security / controls / RMF
    controls: Optional[Controls] = None
    cac: Optional[CAC] = None
    test_results: Optional[TestResults] = None
    findings: Optional[Findings] = None
    poam_dashboard: Optional[SystemPOAMDashboard] = None

    # System rollup / metadata
    system_info: Optional[SystemInfo] = None
    system_details_dashboard: Optional[SystemDetailsDashboard] = None
    associations: Optional[Associations] = None

    # Workflow / package / AO approval trail
    workflow_dashboard: Optional[WorkflowDashboard] = None
    workflows: Optional[Workflows] = None

    # Contacts / people
    user_details: Optional[UserDetails] = None


class SystemContext(BaseModel):
    """
    One authoritative snapshot of a single system (identified by system_id).

    This model is what downstream tests / UI consume.
    - Promotes key scalars (CIA levels, workflow stage, cloud flags, etc.).
    - Holds structured submodels for each major eMASS surface.
    - Optionally carries `raw_payloads` for full-fidelity debugging / traceability.

    All fields are Optional unless they are fundamental identity/path info.
    We intentionally allow partial / dirty data because eMASS exports are messy.
    """

    # -----------------------
    # Identity / file paths
    # -----------------------
    system_id: int
    data_path: str
    checklist_path: str
    demo_assets: Optional[str] = None

    # -----------------------
    # Core descriptive info
    # -----------------------
    system_name: Optional[str] = None
    system_acronym: Optional[str] = None
    system_description: Optional[str] = None
    system_version: Optional[str] = None

    registration_type: Optional[str] = None
    lifecycle_phase: Optional[str] = None
    authorization_status: Optional[str] = None

    # CIA triad / impact posture
    confidentiality: Optional[str] = Field(
        default=None,
        description="Confidentiality impact level (Low | Moderate | Medium | High).",
    )
    integrity: Optional[str] = None
    availability: Optional[str] = None
    impact: Optional[str] = None
    system_type: Optional[str] = None
    rmf_activity: Optional[str] = None

    mission_criticality: Optional[str] = None
    classification: Optional[str] = None  # Highest data classification

    # -----------------------
    # APMS / crosswalk info
    # -----------------------
    apms_item_name: Optional[str] = None
    apms_acronym: Optional[str] = None
    data_report_number: Optional[str] = None       # External tracking / DRN / etc.
    emass_data_id: Optional[str] = None            # eMASS <-> APMS linkage ID

    # Snapshot of APMS CSV columns / first row for traceability
    apms_headers_raw: Optional[List[str]] = None
    apms_first_row_raw: Optional[Dict[str, Any]] = None

    # -----------------------
    # Cloud / hosting / connectivity
    # -----------------------
    cloud_computing: Optional[bool] = None
    cloud_type: Optional[str] = None
    is_saas: Optional[bool] = None
    is_paas: Optional[bool] = None
    is_iaas: Optional[bool] = None
    other_service_models: Optional[str] = None

    apms_cloud_assessment_designation: Optional[str] = None
    apms_is_saas_system: Optional[str] = None
    apms_cloud_service_type: Optional[str] = None
    connectivity_ccsd_connectivity: Optional[str] = None

    # -----------------------
    # Data sensitivity flags
    # -----------------------
    cui: Optional[bool] = None   # CUI present?
    pii: Optional[bool] = None   # PII present?
    phi: Optional[bool] = None   # PHI present?
    nss: Optional[bool] = None   # National Security System?
    fms: Optional[bool] = None   # Financial Management System?

    # -----------------------
    # Workflow / RMF status
    # -----------------------
    workflow_type: Optional[str] = None
    workflow_name: Optional[str] = None
    workflow_stage: Optional[str] = None

    # Quick presence hints / rollups
    has_hardware_data: Optional[bool] = None
    has_software_data: Optional[bool] = None
    artifact_number: Optional[int] = None
    has_artifact_details: Optional[bool] = None

    # -----------------------
    # Authorization / continuity / compliance posture
    # These come from SystemInfo and SystemDetails-style dashboards,
    # but callers want them at top-level for reporting.
    # -----------------------

    # When does current authorization expire / terminate?
    auth_termination_epoch: Optional[Any] = None  # usually epoch-ish int/string from eMASS

    # BCDR / contingency planning
    maximum_tolerable_downtime: Optional[str] = None  # MTD
    recovery_time_objective: Optional[str] = None     # RTO
    recovery_point_objective: Optional[str] = None    # RPO

    incident_response_plan_required: Optional[Any] = None
    incident_response_plan_artifact: Optional[str] = None

    # Privacy / statutory artifacts
    pia_required: Optional[Any] = None   # Privacy Impact Assessment required?
    sorn_required: Optional[Any] = None  # System of Records Notice required?
    eauth_required: Optional[Any] = None # eAuth Risk Assessment required?

    # ATC (Authorization To Connect) data
    atc_decision: Optional[str] = None
    atc_decision_date: Optional[Any] = None
    atc_termination_date: Optional[Any] = None

    # -----------------------
    # Parsed endpoint payloads
    # Each of these is one model defined above.
    # -----------------------

    # System overview / identity / registration / classification
    system_info: Optional["SystemInfo"] = None
    system_details_dashboard: Optional["SystemDetailsDashboard"] = None

    # Workflow / package lifecycle
    workflow_dashboard: Optional["WorkflowDashboard"] = None
    workflows: Optional["Workflows"] = None
    cac: Optional["CAC"] = None  # control assessment chain / compliance lifecycle

    # Security posture / controls / assessment results
    controls: Optional["Controls"] = None
    test_results: Optional["TestResults"] = None
    findings: Optional["Findings"] = None
    privacy: Optional["Privacy"] = None

    # Evidence / artifacts / POA&M
    artifact_details: Optional["ArtifactDetails"] = None
    artifact_summary: Optional["ArtifactSummary"] = None
    system_poam_dashboard: Optional["SystemPOAMDashboard"] = None

    # Inventory / assets
    hardware: Optional["Hardware"] = None
    hardware_details_dashboard: Optional["HardwareDetailsDashboard"] = None
    software: Optional["Software"] = None
    software_details_dashboard: Optional["SoftwareDetailsDashboard"] = None

    # Org / ownership / people / relationships
    associations: Optional["Associations"] = None
    user_details: Optional["UserDetails"] = None

    # -----------------------
    # Raw payloads for trace/debug
    # We populate this if/only-if the caller wants full fidelity for audits.
    # -----------------------
    raw_payloads: Optional["RawPayloads"] = None

    class Config:
        extra = "ignore"


# --- Conversion helpers ---
def _to_bool(value: Any) -> Optional[bool]:
    """
    Convert flexible truthy/falsy values into a boolean or None.

    Args:
        value (Any): Raw input (bool, str, int, etc.).

    Returns:
        bool | None: True, False, or None if indeterminate.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in {"true", "yes", "y", "1"}:
        return True
    if s in {"false", "no", "n", "0"}:
        return False
    return None


def _to_int(value: Any) -> Optional[int]:
    """
    Convert input into an integer if possible.

    Args:
        value (Any): Raw input.

    Returns:
        int | None: Parsed integer or None if invalid.
    """
    try:
        return int(value) if value is not None and str(value).strip() != "" else None
    except Exception:
        return None
