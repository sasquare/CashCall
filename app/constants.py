"""
Central constants file.
Departments stored as strings (not DB enum) to avoid migration pain.
"""

# ---------------------------------------------------------------------------
# DEPARTMENT HIERARCHY
# ---------------------------------------------------------------------------

DEPARTMENT_GROUPS: dict[str, list[str]] = {
    "DPRP – Corporate & Support": [
        "DPRP-Human Resource Department",
        "DPRP-Training and Development",
        "DPRP-Sales & Marketing General",
        "DPRP-GVP Office",
        "DPRP-Legal",
        "DPRP-Internal Audit",
        "DPRP-Business Development",
        "DPRP-Information Technology",
        "DPRP-Finance & Accounts Department",
        "DPRP-Admin Department",
        "DPRP-Security Department",
        "DPRP-NEPZA Liasion Office",
        "DPRP-Estates",
        "DPRP-Guest House",
        "DPRP-Logistics Dept",
    ],
    "DPRP – Facilities & Residences": [
        "DPRP-Power systems (DG sets, etc)",
        "DPRP-Power systems (DG sets, etc)-Estate",
        "DPRP-10K Residences",
        "DPRP-22K Residences",
        "DPRP-Fleet-Refinery Site",
        "DPRP-Batching Plant",
    ],
    "DPRP – Projects": [
        "DPRP-Project Procurement",
        "DPRP-Local Procurement",
        "DPRP-Project Planning Department",
        "DPRP-Project Control & QA Department",
        "DPRP-Field Engineering-Civil Department",
        "DPRP-Field Engineering-Mech Department",
        "DPRP-Field Engineering-Electrical Dept",
        "DPRP-Field Engineering-Opera Department",
        "DPRP-Lifting Eqipment(Cranes, Rigs,etc.)",
        "DPRP-Project Stores and Material",
        "DPRP-Project Documentation Depart",
        "DPRP-Health, Safety and Environmen",
        "DPRP-Mines and HEM Machines Depart",
    ],
    "DPRP – Gas & Industrial Plants": [
        "DPRP-Oxygen Plant General expenses",
        "DPRP-Oxgn Plant power cos",
        "DPRP-Oxgn Plant Transport co",
        "DPRP-Oxgn Plant Manpower cost",
        "DPRP-Acetylene Plant General E",
        "DPRP-Acetyln Plant power cost",
        "DPRP-Acetyln Plant Transport cos",
        "DPRP-Acetyln Plant Raw Material cost",
        "DPRP-Acetyln Plant Man power cost",
        "DPRP-New Block Making Plant General Exps",
        "DPRP-New Block Making Plant power cost",
        "DPRP-New Block Plant Transport cost",
        "DPRP-New Block Plant Manpower cost",
        "DPRP-New Block Plant Raw material Cost",
        "DPRP-Old Block Making Plant General Exps",
        "DPRP-Old Block Making Plant power cost",
        "DPRP-Old Block Plant Transport cost",
        "DPRP-Old Block Plant Manpower cost",
        "DPRP-Old Block Plant Raw material Cost",
        "DPRP-Nitrogen Plant General Exps",
        "DPRP-Nitrogen Plant power cost",
        "DPRP-Nitrogen Plant Transport cost",
        "DPRP-Nitrogen Plant Raw Material cost",
        "DPRP-Nitrogen Plant Man power cost",
    ],
    "DPRP – Marine": [
        "DPRP-Marine Control Room",
        "DPRP-Jetty",
        "DPRP-Marine-Mechanical",
        "DPRP-Marine-Electrical",
        "DPRP-Marine-Instrumentation",
        "DPRP-Marine-Operation",
    ],
    "DORC – Corporate & Support": [
        "DORC-GED Office",
        "DORC-Legal",
        "DORC-Internal Audit",
        "DORC-Business Development",
        "DORC-Information Technology",
        "DORC-EWOGGS",
        "DORC-WAEPC",
        "DORC-Finance And Accounts",
        "DORC-Treasury",
        "DORC-Human Resources",
        "DORC-Training and Development",
        "DORC-Administration Department",
        "DORC-Security",
        "DORC-NEPZA Liasion Office",
        "DORC-Group Vice President Office",
        "DORC-Human Resource",
    ],
    "DORC – Facilities": [
        "DORC - Drivers",
        "DORC - Estates",
        "DORC-Dispensary",
        "DORC-Guest Houses",
        "DORC-DG Sets",
        "DORC-DG Sets - Estates",
        "DORC-Fleet at Site",
    ],
    "Refinery – Workshop & Common Services": [
        "Refinery Workshop - Mechanical",
        "Refinery Workshop - Electrical",
        "Refinery Workshop - Instrumentation",
        "Refinery Workshop - Mechanical Common",
        "Refinery Workshop - Electrical Common",
        "Refinery Workshop - Inst Common",
        "Refinery Workshop - Civil Common",
        "Central engineering services",
        "Central Technical Services",
        "Fire and Safety",
        "Support Services (Warhouse & Logistics)",
        "Refinery Laboratory",
        "Refinery Fire Station",
        "Refinery Ware House",
        "Refinery Mecial Centre",
        "Refinery Administrative Building",
        "Refinery Computer Centre",
        "Refinery Canteen",
        "Refinery Training Centre",
        "Refinery Communication",
    ],
    "Refinery – Tank Farm & Offsite": [
        "Tank Farm – Mechanical",
        "Tank Farm – Electrical",
        "Tank Farm – Instrumentation",
        "Tank Farm – Others",
        "Crude Storage & Pumping",
        "Intermediate Storage & Pumps",
        "LPG/C3 Storage",
        "Other Product Storage",
        "Sulfur Pelletisation & Liquid Sulfur Sto",
        "Gasoline Blending",
        "Other offsite facility - Mechanical",
        "Other offsite facility – Electrical",
        "Other offsite facility – Instrumentation",
        "Other offsite facility – Others",
        "Effluent Treatment Plant",
        "Wet Air Oxidation",
        "Oil Water/Storm Water Sewer",
        "Fire Water System",
        "Plant Buildings",
        "Gantry",
        "Road Loading Facilities",
        "SPM & Offshore Facilities & Product Pipe",
        "Control Room Building",
        "Crude Pipelines & Trading Facilities",
    ],
    "Refinery – Power Block": [
        "Power Block - Mechanical",
        "Power Block- Electrical",
        "Power Block -Instrumentation",
        "Power Block- Others",
        "CPP,GT,HRSG,STG,Utility Boiler, BFW(681)",
        "Re-circulating Water System-1 (CPP)(682)",
    ],
    "Refinery – Alkylation Block": [
        "Alkylation Block - Mechanical",
        "Alkylation Block - Electrical",
        "Alkylation Block -Instrumentat",
        "Alkylation Block -Others",
        "Butamer Process Unit (141)",
        "Sulfuric Acid Alkylation Unit (142)",
        "Sulphuric Acid Regeneration Process(143)",
        "HUELS Selective Hydrogenation Proces 144",
        "Common Facilities for SHP & Butamer(145)",
    ],
    "Refinery – Crude Distillation": [
        "Crude Distillation Unit - Mechanical",
        "Crude Distillation Unit - Electrical",
        "Crude Distillati Unit - Instrumentation",
        "Crude Distillation Unit - Others",
        "Crude Distillation SubUnit (101) Operat",
        "Saturate Gas ConcentrationSub Unit (102)",
        "Saturated LPG Merox SubUnit (103) SLMU",
        "Saturated LPG Merox Unit (104) SLMU",
    ],
    "Refinery – Diesel Hydrotreating": [
        "Diesel Hydrotreating Block - Mechanical",
        "Diesel Hydrotreating Block - Electrical",
        "Diesel Hydrotreating Block -Instrumentat",
        "Diesel Hydrotreating Block -Others",
        "Diesel Hydrotreating SubUnit",
        "Diesel Product to Storage subunit 121",
        "Diesel MHC SubUnit 120 & Misc.",
    ],
    "Refinery – RFCC Block": [
        "RFCC Block - Mechanical",
        "RFCC Block - Electrical",
        "RFCC Block - Instrumentation",
        "RFCC Block - Others",
        "Reactor-Regenerator Section (111)",
        "Main Column Section (112)",
        "UOP Gas Concentration Process Unit (113)",
        "Propylene Recovery Unit (PRU) (114)",
        "Power Recovery System (115)",
        "Unsaturated LPG MeroxProcess Unit (116)",
        "C5 Extraction Merox Process Unit (132)",
    ],
    "Refinery – Gasoline & Hydrogen": [
        "Gasoline Block - Mechanical",
        "Gasoline Block - Electrical",
        "Gasoline Block -Instrumentation",
        "Gasoline Block -Others",
        "Scanfining Unit (133)",
        "Hydrogen Plant - Mechanical",
        "Hydrogen Plant - Electrical",
        "Hydrogen Plant - Instrumentation",
        "Hydrogen Plant - Others",
        "Hydrogen Generation Sub UnitT1 (161)",
        "Hydrogen Gene USub nit Train 2 (162)",
    ],
    "Refinery – MS Block": [
        "MS Block - Mechanical",
        "MS Block - Electrical",
        "MS Block - Instrumentation",
        "MS Block - Others",
        "Naphtha Hydrotreating Sub Unit (151)",
        "CCR Platforming Sub Unit (152)",
        "CCR - Regen Section Sub Unit (153)",
        "Penex Sub Unit (155)",
    ],
    "Refinery – Polymer Block": [
        "Polymer Block - Mechanical",
        "Polymer Block- Electrical",
        "Polymer Block -Instrumentation",
        "Polymer Block- Others",
        "PolyPropylene Unit Train-1 (171)",
        "PolyPropylene Unit Train-2 (172)",
        "Polymer Bagging and Packaging (173)",
    ],
    "Refinery – Sulphur Block": [
        "Sulphur Block - Mechanical",
        "Sulphur Block- Electrical",
        "Sulphur Block -Instrumentation",
        "Sulphur Block- Others",
        "Non-Phenolic Sour Water Stripper(181)",
        "Phenolic Sour Water Stripper Unit (182)",
        "Amine Regeneration Unit (Unsatur)(183)",
        "Amine Regeneration Unit (Saturated)(184)",
        "Sulphur Recovery Unit-I&Common facil(185)",
        "Sulphur Recovery Unit-II (186)",
        "Caustic Scrubber (HOLD) (187)",
    ],
    "Refinery – Utilities": [
        "Utility Block - Mechanical",
        "Utility Block- Electrical",
        "Utility Block -Instrumentation",
        "Utility Block- Others",
        "Instrument / Plant Air System (612)",
        "Nitrogen Unit",
        "Treated Raw Water system (621)",
        "DM Water Plant (622)",
        "Cooling Water system (631)",
        "Cooling Water CT2 system (632)",
        "Cooling Water CT3 system (633)",
        "Cooling Water CT4 system (634)",
        "Internal Fuel Oil / Fuel Gas System(651)",
    ],
}

# Flat list for validation — single source of truth
ALL_DEPARTMENTS: list[str] = [
    dept for depts in DEPARTMENT_GROUPS.values() for dept in depts
]

# ---------------------------------------------------------------------------
# CASH CALL CATEGORIES
# ---------------------------------------------------------------------------

CASH_CALL_CATEGORIES: list[str] = [
    "Catalyst & Chemicals",
    "Crude Shipping / Marine",
    "Maintenance Cost",
    "Admin & Insurance",
    "Communication / Internet",
]

# ---------------------------------------------------------------------------
# CURRENCIES
# ---------------------------------------------------------------------------

CURRENCIES: list[str] = ["USD", "NGN", "EUR", "GBP", "INR"]

# ---------------------------------------------------------------------------
# USER ROLES
# ---------------------------------------------------------------------------

USER_ROLES: list[str] = [
    "originator",
    "hod",
    "finance_reviewer",
    "cfo",
    "ceo",
    "treasury",
    "it_admin",
]

# ---------------------------------------------------------------------------
# SUBMISSION STATUSES
# ---------------------------------------------------------------------------

SUBMISSION_STATUSES: list[str] = [
    "pending_hod",
    "pending_finance_qc",
    "qc_query_raised",
    "pending_cfo",
    "pending_ceo",
    "ceo_approved",
    "declined_by_hod",
    "declined_by_cfo",
    "declined_by_ceo",
    "returned_for_revision",
    "returned_by_cfo",
    "deferred_by_cfo",
    "deferred_by_cio",
    "pending_treasury_payment",
    "paid",
]

TREASURY_PAYMENT_STATUSES: list[str] = [
    "paid",
    "not_yet_paid",
    "doc_not_in_treasury",
    "returned_to_payable",
    "duplicated",
    "audit_hold",
    "invoice_not_received",
    "account_payable",
    "other",
]

ARREAR_TYPES: list[str] = [
    "prior_period",
    "bluestar_shipping",
    "ge_international",
    "rfcc_shutdown",
    "expansion_project",
]

PAYMENT_FREQUENCIES: list[str] = [
    "one_off",
    "monthly",
    "quarterly",
    "annual",
]

COST_TYPES: list[str] = ["opex", "capex"]

URGENCY_CATEGORIES: list[str] = [
    "Plant Shutdown Risk",
    "Safety & Regulatory Compliance",
    "Contractual Obligation / Penalty Avoidance",
    "Supplier Credit Risk",
    "Critical Spare Parts",
    "Utility / Feedstock Continuity",
    "Other",
]

# Status → badge colour mapping (used in templates)
STATUS_BADGE_COLOURS: dict[str, str] = {
    "pending_hod": "amber",
    "pending_finance_qc": "amber",
    "qc_query_raised": "purple",
    "pending_cfo": "amber",
    "pending_ceo": "amber",
    "ceo_approved": "green",
    "declined_by_hod": "red",
    "declined_by_cfo": "red",
    "declined_by_ceo": "red",
    "returned_for_revision": "purple",
    "returned_by_cfo": "purple",
    "deferred_by_cfo": "gray",
    "deferred_by_cio": "gray",
    "pending_treasury_payment": "amber",
    "paid": "green",
}

MONTH_NAMES: dict[int, str] = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}
