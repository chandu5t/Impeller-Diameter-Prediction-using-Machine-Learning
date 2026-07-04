"""
FastAPI service for pump impeller diameter prediction (v3 pipeline).

Only one artifact is required:
    pump_pipeline_v3.pkl — sklearn Pipeline (preprocessor + model), saved with joblib.

Feature names and column order are read from the fitted ColumnTransformer inside that
pipeline (same information the old model_config_v3.pkl duplicated).

Optional: Impeller_Dataset.xlsx at DATASET_PATH for reference row lookup.

Serving env: scikit-learn must match the version used to joblib.dump the pipeline
(see requirements.txt). Mismatch causes unpickle errors (e.g. _RemainderColsList).
"""

from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = Path(os.environ.get("MODEL_DIR", str(BASE_DIR / "models")))
PIPELINE_PATH = Path(os.environ.get("PIPELINE_FILE", str(MODEL_DIR / "pump_pipeline_v3.pkl")))
DATASET_PATH = Path(
    os.environ.get(
        "DATASET_PATH",
        str(BASE_DIR.parent / "Impeller_Dataset.xlsx"),
    )
)

app = FastAPI(title="Pump Impeller Prediction API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_pipeline: Any = None
_feature_meta: dict[str, Any] | None = None
_dataset_df: pd.DataFrame | None = None
_dataset_load_error: str | None = None


def _find_column_transformer(pipeline: Any) -> Any:
    """Locate the sklearn ColumnTransformer used as preprocessing."""
    if not hasattr(pipeline, "named_steps"):
        raise ValueError("Loaded object is not a sklearn Pipeline.")
    for name in ("preprocessor", "prep", "column_transformer", "transformer"):
        step = pipeline.named_steps.get(name)
        if step is not None and hasattr(step, "transformers_"):
            return step
    for _, step in pipeline.named_steps.items():
        if hasattr(step, "transformers_") and hasattr(step, "named_transformers_"):
            return step
    raise ValueError(
        "Could not find a ColumnTransformer (no step with transformers_). "
        "Expected a step named 'preprocessor' or similar."
    )


def derive_feature_layout(pipeline: Any) -> dict[str, Any]:
    """
    Reconstruct feature lists from the fitted pipeline (matches training notebook:
    categoricals first in the input DataFrame, then numerics).
    """
    ct = _find_column_transformer(pipeline)
    cat_cols: list[str] = []
    num_cols: list[str] = []

    for name, _trans, cols in ct.transformers_:
        if name == "remainder" or cols is None:
            continue
        cols_list = list(cols)
        if name == "cat":
            cat_cols = cols_list
        elif name == "num":
            num_cols = cols_list

    if not cat_cols and not num_cols:
        raise ValueError(
            "ColumnTransformer has no 'cat' / 'num' branches with column names. "
            "Check that the saved pipeline matches the v3 notebook structure."
        )

    all_input = cat_cols + num_cols
    return {
        "categorical_features": cat_cols,
        "numeric_features": num_cols,
        "all_input_features": all_input,
        # Targets are not stored on the regressor; names match the training notebook.
        "target_columns": ["Full_Diameter", "Trimmed_Diameter"],
    }


def extract_categorical_options(pipeline: Any, categorical_features: list[str]) -> dict[str, list[str]]:
    """Read OrdinalEncoder category lists from the fitted preprocessing step."""
    try:
        ct = _find_column_transformer(pipeline)
        enc = ct.named_transformers_.get("cat")
        if enc is None or not hasattr(enc, "categories_"):
            return {c: [] for c in categorical_features}
        out: dict[str, list[str]] = {}
        for i, col in enumerate(categorical_features):
            if i >= len(enc.categories_):
                out[col] = []
                continue
            cats = enc.categories_[i]
            out[col] = [str(x) for x in cats]
        return out
    except Exception:
        return {c: [] for c in categorical_features}


def load_artifacts() -> tuple[Any, dict[str, Any]]:
    global _pipeline, _feature_meta
    if _pipeline is not None and _feature_meta is not None:
        return _pipeline, _feature_meta
    if not PIPELINE_PATH.is_file():
        raise FileNotFoundError(
            f"Missing pipeline file: {PIPELINE_PATH}. "
            "Copy pump_pipeline_v3.pkl into backend/models/ (or set PIPELINE_FILE)."
        )
    _pickle_version_hint = (
        " Joblib/sklearn pickles are not portable across sklearn versions. "
        "From the backend folder run: pip install -r requirements.txt "
        "(pins scikit-learn to the training version), or re-export the model "
        "using the same sklearn you have in production."
    )
    try:
        loaded = joblib.load(PIPELINE_PATH)
    except (AttributeError, ModuleNotFoundError, pickle.UnpicklingError) as e:
        raise RuntimeError(
            f"Failed to load pipeline pickle ({type(e).__name__}: {e}).{_pickle_version_hint}"
        ) from e
    except Exception as e:
        if "_RemainderColsList" in str(e) or "Can't get attribute" in str(e):
            raise RuntimeError(
                f"Failed to load pipeline pickle ({type(e).__name__}: {e}).{_pickle_version_hint}"
            ) from e
        raise
    _feature_meta = derive_feature_layout(loaded)
    _pipeline = loaded
    return _pipeline, _feature_meta


def load_dataset() -> None:
    global _dataset_df, _dataset_load_error
    if _dataset_df is not None or _dataset_load_error is not None:
        return
    if not DATASET_PATH.is_file():
        _dataset_load_error = f"No dataset file at {DATASET_PATH}"
        return
    try:
        df = pd.read_excel(DATASET_PATH)
        if "Special_Instruction" in df.columns:
            df["Special_Instruction"] = df["Special_Instruction"].fillna("NONE")
        _dataset_df = df
    except Exception as e:
        _dataset_load_error = str(e)


def estimate_pump_power_kw(
    flow_m3h: float, total_head_m: float, pump_efficiency_pct: float
) -> float:
    """Hydraulic power / efficiency as a kW estimate when shaft power is unknown."""
    if pump_efficiency_pct <= 0:
        raise ValueError("Pump efficiency must be positive.")
    q_m3s = flow_m3h / 3600.0
    p_hyd_kw = 1000.0 * 9.81 * q_m3s * total_head_m / 1000.0
    return float(p_hyd_kw / (pump_efficiency_pct / 100.0))


class PredictRequest(BaseModel):
    pump_type: str
    impeller_moc: str
    impeller_moc_confirm: str
    diffuser_moc: str
    diffuser_moc_confirm: str
    special_instruction: str = "NONE"
    head_per_chamber: float = Field(..., gt=0)
    number_of_chambers: float = Field(..., gt=0)
    speed_rpm: float = Field(..., gt=0)
    flow_m3h: float = Field(..., ge=0)
    pump_efficiency: float = Field(..., gt=0, le=100)
    total_head: float = Field(..., ge=0)
    pump_power_kw: float | None = None

    @field_validator("special_instruction", mode="before")
    @classmethod
    def empty_special_to_none(cls, v: Any) -> str:
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return "NONE"
        return str(v).strip()


class PredictResponse(BaseModel):
    full_diameter_mm: float
    trimmed_diameter_mm: float
    pump_power_used_kw: float
    pump_power_was_estimated: bool
    message: str | None = None


class DatasetMatchRequest(BaseModel):
    pump_type: str
    impeller_moc: str
    diffuser_moc: str
    special_instruction: str = "NONE"
    head_per_chamber: float
    number_of_chambers: float
    speed_rpm: float
    flow_m3h: float
    pump_efficiency: float
    total_head: float
    pump_power_kw: float | None = None
    match_mode: str = "close"

    @field_validator("special_instruction", mode="before")
    @classmethod
    def empty_special(cls, v: Any) -> str:
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return "NONE"
        return str(v).strip()


@app.on_event("startup")
def startup() -> None:
    load_dataset()
    try:
        load_artifacts()
        import sklearn

        print(f"[startup] Model loaded (scikit-learn {sklearn.__version__})")
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"[startup] Model not loaded: {e}")


@app.get("/api/health")
def health() -> dict[str, Any]:
    import sklearn

    try:
        load_artifacts()
        model_ok = True
        model_msg = "ready"
    except (FileNotFoundError, ValueError, OSError, RuntimeError) as e:
        model_ok = False
        model_msg = str(e)
    load_dataset()
    ds_ok = _dataset_df is not None
    return {
        "status": "ok" if model_ok else "degraded",
        "model_loaded": model_ok,
        "model_message": model_msg,
        "sklearn_version_runtime": sklearn.__version__,
        "config_source": "derived_from_pipeline",
        "dataset_loaded": ds_ok,
        "dataset_path": str(DATASET_PATH),
        "dataset_message": None if ds_ok else (_dataset_load_error or "not loaded"),
    }


@app.get("/api/options")
def get_options() -> dict[str, Any]:
    try:
        pipeline, meta = load_artifacts()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    cats = meta.get("categorical_features", [])
    opts = extract_categorical_options(pipeline, cats)
    return {
        "categorical_features": meta.get("categorical_features", []),
        "numeric_features": meta.get("numeric_features", []),
        "target_columns": meta.get("target_columns", []),
        "options": {
            "Pump_Type": opts.get("Pump_Type", []),
            "Impeller_MOC": opts.get("Impeller_MOC", []),
            "Diffuser_MOC": opts.get("Diffuser_MOC", []),
            "Special_Instruction": opts.get("Special_Instruction", []),
        },
    }


@app.post("/api/predict", response_model=PredictResponse)
def predict(req: PredictRequest) -> PredictResponse:
    try:
        pipeline, meta = load_artifacts()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    if req.impeller_moc != req.impeller_moc_confirm:
        raise HTTPException(
            status_code=400,
            detail="Impeller MOC confirmation does not match the first selection.",
        )
    if req.diffuser_moc != req.diffuser_moc_confirm:
        raise HTTPException(
            status_code=400,
            detail="Diffuser MOC confirmation does not match the first selection.",
        )

    power_estimated = False
    pump_power = req.pump_power_kw
    if pump_power is None or pump_power <= 0:
        try:
            pump_power = estimate_pump_power_kw(
                req.flow_m3h, req.total_head, req.pump_efficiency
            )
            power_estimated = True
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    row = {
        "Pump_Type": req.pump_type,
        "Impeller_MOC": req.impeller_moc,
        "Diffuser_MOC": req.diffuser_moc,
        "Special_Instruction": req.special_instruction,
        "Head_per_Chamber": req.head_per_chamber,
        "Number_of_Chambers": req.number_of_chambers,
        "Speed_RPM": req.speed_rpm,
        "Flow_m3h": req.flow_m3h,
        "Pump_Efficiency": req.pump_efficiency,
        "Total_Head": req.total_head,
        "Pump_Power": pump_power,
    }
    order = meta["all_input_features"]
    try:
        X = pd.DataFrame([row])[order]
        pred = pipeline.predict(X)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Prediction failed: {type(e).__name__}: {e}",
        ) from e

    full_d = float(pred[0][0])
    trim_d = float(pred[0][1])
    msg = None
    if power_estimated:
        msg = "Pump power was estimated from flow, head, and efficiency (hydraulic power / efficiency)."

    return PredictResponse(
        full_diameter_mm=full_d,
        trimmed_diameter_mm=trim_d,
        pump_power_used_kw=float(pump_power),
        pump_power_was_estimated=power_estimated,
        message=msg,
    )


def _filter_matching_rows(
    df: pd.DataFrame,
    req: DatasetMatchRequest,
    rtol: float = 1e-4,
    atol: float = 1e-3,
) -> pd.DataFrame:
    mask = (
        (df["Pump_Type"].astype(str) == str(req.pump_type))
        & (df["Impeller_MOC"].astype(str) == str(req.impeller_moc))
        & (df["Diffuser_MOC"].astype(str) == str(req.diffuser_moc))
    )
    if "Special_Instruction" in df.columns:
        mask = mask & (
            df["Special_Instruction"].fillna("NONE").astype(str)
            == str(req.special_instruction)
        )
    out = df.loc[mask].copy()
    if req.match_mode == "exact":
        num_cols = [
            ("Head_per_Chamber", req.head_per_chamber),
            ("Number_of_Chambers", req.number_of_chambers),
            ("Speed_RPM", req.speed_rpm),
            ("Flow_m3h", req.flow_m3h),
            ("Pump_Efficiency", req.pump_efficiency),
            ("Total_Head", req.total_head),
            ("Pump_Power", req.pump_power_kw),
        ]
        for col, val in num_cols:
            if col not in out.columns:
                return pd.DataFrame()
            out = out[np.isclose(out[col].astype(float), float(val), rtol=rtol, atol=atol)]
        return out

    num_cols = [
        ("Head_per_Chamber", req.head_per_chamber),
        ("Number_of_Chambers", req.number_of_chambers),
        ("Speed_RPM", req.speed_rpm),
        ("Flow_m3h", req.flow_m3h),
        ("Pump_Efficiency", req.pump_efficiency),
        ("Total_Head", req.total_head),
        ("Pump_Power", req.pump_power_kw),
    ]
    for col, val in num_cols:
        if col not in out.columns:
            return pd.DataFrame()
        out = out[
            np.isclose(out[col].astype(float), float(val), rtol=0.02, atol=0.05)
        ]
    return out


@app.post("/api/dataset-matches")
def dataset_matches(req: DatasetMatchRequest) -> dict[str, Any]:
    load_dataset()
    if _dataset_df is None:
        raise HTTPException(
            status_code=503,
            detail=_dataset_load_error or "Dataset not available.",
        )
    power = req.pump_power_kw
    if power is None or power <= 0:
        try:
            power = estimate_pump_power_kw(
                req.flow_m3h, req.total_head, req.pump_efficiency
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
    req_kw = req.model_copy(update={"pump_power_kw": power})
    try:
        matches = _filter_matching_rows(_dataset_df, req_kw)
        max_rows = 200
        total = len(matches)
        matches = matches.head(max_rows)
        records = matches.replace({np.nan: None}).to_dict(orient="records")
        return {
            "count": total,
            "returned": len(records),
            "truncated": total > max_rows,
            "rows": records,
        }
    except KeyError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Dataset is missing expected columns: {e}",
        ) from e


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
