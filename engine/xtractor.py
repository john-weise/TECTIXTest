#!/usr/bin/env python3
"""
xtractor.py

Schema discovery for eMASS-ish JSON fixtures.

- Scans Notionalassets/ for *.json
- Infers structure and nested models
- Writes:
    1) T_model.txt  -> Pydantic-ish models (cleaned: no pagination/meta by default)
    2) T_model.json -> machine-friendly schema (includes everything)

Key differences from the naive version:
- We treat "data" as the payload and "meta"/"pagination" as transport noise.
- We make fields Optional[...] so we don't blow up on partial exports.
- We keep discovered structure in JSON so you can push it into Postgres later.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Union,
    Literal,
)

# ---------------------------------------------------------------------------
# CONFIG / HEURISTICS
# ---------------------------------------------------------------------------

# fields we often see in eMASS that are "transport" not "business"
WRAPPER_FIELDS: Set[str] = {"meta", "pagination"}
PAYLOAD_FIELDS: Set[str] = {"data", "results", "items"}

# how many dynamic keys before we call a dict "Dict[str, Any]"
DYNAMIC_KEY_THRESHOLD = 2

logging.basicConfig(level=logging.INFO, format="[xtractor] %(message)s")
LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PATH HELPERS
# ---------------------------------------------------------------------------

def get_repo_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, ".."))


def get_notionalassets_dir() -> str:
    repo_root = get_repo_root()
    candidates = [
        os.path.join(repo_root, "engine", "Notionalassets"),
        os.path.join(repo_root, "Notionalassets"),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return os.path.abspath(c)
    return os.path.abspath(candidates[0])


def get_output_txt_path() -> str:
    return os.path.join(get_repo_root(), "T_model.txt")


def get_output_json_path() -> str:
    return os.path.join(get_repo_root(), "T_model.json")


# ---------------------------------------------------------------------------
# NAME HELPERS
# ---------------------------------------------------------------------------

def normalize_field_name(raw: str) -> str:
    s = raw.strip().lower()
    s = re.sub(r"[ \-\/]+", "_", s)
    s = re.sub(r"[^0-9a-zA-Z_]", "", s)
    s = re.sub(r"__+", "_", s)
    if not s:
        s = "_unnamed"
    if re.match(r"^[0-9]", s):
        s = "_" + s
    return s


def to_camel(name: str) -> str:
    parts = re.split(r"[^0-9a-zA-Z]+", name)
    parts = [p for p in parts if p]
    if not parts:
        return "Model"
    out: List[str] = []
    for p in parts:
        if p.isupper():
            out.append(p)
        else:
            out.append(p[:1].upper() + p[1:].lower())
    return "".join(out)


def class_name_from_filename(filename: str) -> str:
    base = os.path.splitext(os.path.basename(filename))[0]
    return to_camel(base)


# ---------------------------------------------------------------------------
# DYNAMIC MAP HEURISTICS
# ---------------------------------------------------------------------------

def looks_like_dynamic_key(key: str) -> bool:
    key = str(key)
    if len(key) > 28:
        return True
    if re.match(r"^[0-9a-f]{16,}$", key, re.IGNORECASE):
        return True
    return False


def dict_is_probably_map(d: Dict[str, Any]) -> bool:
    if not d:
        return False
    keys = list(d.keys())
    dyn = sum(1 for k in keys if looks_like_dynamic_key(k))
    return dyn >= max(DYNAMIC_KEY_THRESHOLD, len(keys) // 2)


# ---------------------------------------------------------------------------
# SCHEMA DATA STRUCTURES
# ---------------------------------------------------------------------------

@dataclass
class SchemaField:
    name: str
    type_str: str
    original_keys: Set[str] = field(default_factory=set)
    examples: List[Any] = field(default_factory=list)

    def merge(self, other: "SchemaField") -> None:
        self.type_str = merge_type_strings(self.type_str, other.type_str)
        self.original_keys.update(other.original_keys)
        for val in other.examples:
            if len(self.examples) < 5:
                self.examples.append(val)


@dataclass
class SchemaModel:
    name: str
    fields: Dict[str, SchemaField] = field(default_factory=dict)

    def add_field(
        self,
        field_name: str,
        type_str: str,
        original_key: Optional[str] = None,
        example: Any = None,
    ) -> None:
        if field_name not in self.fields:
            self.fields[field_name] = SchemaField(
                name=field_name,
                type_str=type_str,
                original_keys={original_key} if original_key else set(),
                examples=[example] if example is not None else [],
            )
            return

        self.fields[field_name].merge(
            SchemaField(
                name=field_name,
                type_str=type_str,
                original_keys={original_key} if original_key else set(),
                examples=[example] if example is not None else [],
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "fields": [
                {
                    "name": f.name,
                    "type": f.type_str,
                    "original_keys": sorted(list(f.original_keys)),
                    "examples": f.examples,
                }
                for f in sorted(self.fields.values(), key=lambda x: x.name)
            ],
        }


# ---------------------------------------------------------------------------
# TYPE INFERENCE
# ---------------------------------------------------------------------------

def infer_scalar_type(value: Any) -> str:
    if value is None:
        return "Optional[Any]"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    return "Any"


def merge_type_strings(a: str, b: str) -> str:
    if a == b:
        return a
    if a == "Any" or b == "Any":
        return "Any"

    def unwrap_opt(t: str) -> Tuple[bool, str]:
        m = re.match(r"Optional\[(.+)\]$", t)
        if m:
            return True, m.group(1)
        return False, t

    a_opt, a_inner = unwrap_opt(a)
    b_opt, b_inner = unwrap_opt(b)

    if a_inner == b_inner:
        return f"Optional[{a_inner}]"

    return f"Union[{a}, {b}]"


# ---------------------------------------------------------------------------
# SCHEMA BUILDING
# ---------------------------------------------------------------------------

def analyze_value(
    value: Any,
    field_name: str,
    parent_model_name: str,
    models: Dict[str, SchemaModel],
) -> str:
    # dict
    if isinstance(value, dict):
        if dict_is_probably_map(value):
            return "Dict[str, Any]"
        submodel_name = f"{parent_model_name}_{to_camel(field_name)}"
        build_schema_from_obj(value, submodel_name, models)
        return submodel_name

    # list
    if isinstance(value, list):
        if not value:
            return "List[Any]"

        contains_dict = any(isinstance(i, dict) for i in value)
        contains_non_dict = any(not isinstance(i, dict) for i in value)

        if contains_dict and not contains_non_dict:
            submodel_name = f"{parent_model_name}_{to_camel(field_name)}Item"
            merged: Dict[str, Any] = {}
            for item in value:
                if isinstance(item, dict):
                    for k, v in item.items():
                        merged.setdefault(k, v)
            build_schema_from_obj(merged, submodel_name, models)
            return f"List[{submodel_name}]"

        if contains_dict and contains_non_dict:
            submodel_name = f"{parent_model_name}_{to_camel(field_name)}Item"
            merged: Dict[str, Any] = {}
            scalar_type: Optional[str] = None
            for item in value:
                if isinstance(item, dict):
                    for k, v in item.items():
                        merged.setdefault(k, v)
                else:
                    st = infer_scalar_type(item)
                    scalar_type = merge_type_strings(scalar_type, st) if scalar_type else st
            if merged:
                build_schema_from_obj(merged, submodel_name, models)
                if scalar_type:
                    return f"List[Union[{submodel_name}, {scalar_type}]]"
                return f"List[{submodel_name}]"
            return f"List[{scalar_type or 'Any'}]"

        # pure scalars
        inner = infer_scalar_type(value[0])
        return f"List[{inner}]"

    # scalar
    return infer_scalar_type(value)


def build_schema_from_obj(
    obj: Any,
    model_name: str,
    models: Dict[str, SchemaModel],
) -> None:
    if model_name not in models:
        models[model_name] = SchemaModel(name=model_name)

    model = models[model_name]

    if isinstance(obj, dict):
        for raw_key, raw_val in obj.items():
            norm_key = normalize_field_name(raw_key)

            # if it's one of the known payload wrappers, we *still* learn it,
            # but we may drop it in the final Pydantic render
            if norm_key in PAYLOAD_FIELDS:
                inner_type = analyze_value(raw_val, norm_key, model_name, models)
                model.add_field(norm_key, inner_type, original_key=raw_key, example=raw_val)
                continue

            if norm_key in WRAPPER_FIELDS:
                # capture but maybe drop later
                inner_type = analyze_value(raw_val, norm_key, model_name, models)
                model.add_field(norm_key, inner_type, original_key=raw_key, example=raw_val)
                continue

            field_type = analyze_value(raw_val, norm_key, model_name, models)
            model.add_field(norm_key, field_type, original_key=raw_key, example=raw_val)

    elif isinstance(obj, list):
        list_type = analyze_value(obj, "data", model_name, models)
        model.add_field("data", list_type, original_key="__root_list__", example=obj)
    else:
        scalar_type = infer_scalar_type(obj)
        model.add_field("value", scalar_type, original_key="__root_scalar__", example=obj)


# ---------------------------------------------------------------------------
# SCAN DIR
# ---------------------------------------------------------------------------

def summarize_json_files(json_dir: str) -> Dict[str, SchemaModel]:
    all_models: Dict[str, SchemaModel] = {}

    for fname in sorted(os.listdir(json_dir)):
        if not fname.lower().endswith(".json"):
            continue

        full = os.path.join(json_dir, fname)
        model_name = class_name_from_filename(fname)

        try:
            with open(full, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as exc:
            LOGGER.warning("Failed to parse %s: %s", full, exc)
            m = SchemaModel(name=model_name)
            m.add_field("__error_parsing_file", "str", example=str(exc))
            all_models[model_name] = m
            continue

        build_schema_from_obj(raw, model_name, all_models)

    return all_models


# ---------------------------------------------------------------------------
# RENDER Pydantic (cleaned)
# ---------------------------------------------------------------------------

def render_models_txt(json_dir: str, model_map: Dict[str, SchemaModel]) -> str:
    """
    Render Pydantic models BUT drop transport noise (meta, pagination).
    Everything is Optional[...] so eMASS weirdness doesn't blow you up.
    """
    lines: List[str] = []
    lines.append("# Auto-generated Pydantic sketch (cleaned)")
    lines.append(f'# Source directory: "{json_dir}"')
    lines.append("from typing import Any, Dict, List, Optional, Union, Literal")
    lines.append("from pydantic import BaseModel, Field")
    lines.append("")
    lines.append('# CIA = Literal["Low", "Moderate", "Medium", "High"]')
    lines.append("CIA = Literal['Low', 'Moderate', 'Medium', 'High']")
    lines.append("")

    for model_name in sorted(model_map.keys()):
        model = model_map[model_name]
        lines.append("# ------------------------------------------------------------")
        lines.append(f"# Source: {model_name}")
        lines.append(f"class {model_name}(BaseModel):")

        # filter out noise fields
        useful_fields = [
            f for f in model.fields.values()
            if f.name not in WRAPPER_FIELDS  # drop meta/pagination
        ]

        if not useful_fields:
            # maybe this model was just meta/pagination; keep a stub
            lines.append("    data: Optional[Any] = None")
            lines.append("")
            continue

        for field in sorted(useful_fields, key=lambda x: x.name):
            # make everything Optional
            type_str = field.type_str
            if not type_str.startswith("Optional["):
                type_str = f"Optional[{type_str}]"
            lines.append(f"    {field.name}: {type_str} = None")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main() -> None:
    repo_root = get_repo_root()
    json_dir = get_notionalassets_dir()
    txt_out = get_output_txt_path()
    json_out = get_output_json_path()

    LOGGER.info("Repo root: %s", repo_root)
    LOGGER.info("Scanning: %s", json_dir)

    model_map = summarize_json_files(json_dir)

    # 1) human-readable Pydantic
    rendered = render_models_txt(json_dir, model_map)
    with open(txt_out, "w", encoding="utf-8") as f:
        f.write(rendered)
    LOGGER.info("Wrote Pydantic sketch to: %s", txt_out)

    # 2) machine-readable
    serial = {
        "source_dir": json_dir,
        "models": [m.to_dict() for m in sorted(model_map.values(), key=lambda m: m.name)],
    }
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(serial, f, indent=2, sort_keys=True)
    LOGGER.info("Wrote JSON schema to: %s", json_out)


if __name__ == "__main__":
    main()
